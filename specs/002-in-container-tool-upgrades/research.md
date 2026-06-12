# Phase 0 Research: In-Container Tool Upgrades

**Feature**: 002-in-container-tool-upgrades
**Date**: 2026-06-12
**Status**: Decisions locked; verification items flagged inline.

This document resolves the implementation unknowns implicit in `spec.md`. There are no `[NEEDS CLARIFICATION]` markers remaining in Technical Context; the items below evaluate alternatives explicitly so the planner doesn't carry hidden assumptions into Phase 1.

---

## R1. Layering model: PATH-ordered overlay vs. derived image

**Decision**: Two-layer install model.
1. **Baseline layer** at `/opt/asdd-baseline/bin/` — installed at image build time, root-owned, immutable for the life of the image.
2. **Project overlay layer** at `/home/asdd/.asdd-tools/bin/` — bind-mounted from `$ASDD_HOME/_state/tools/<project_id>/` on the host, owned by `asdd` (uid 1000).

`PATH=/home/asdd/.asdd-tools/bin:/opt/asdd-baseline/bin:/usr/local/bin:/usr/bin:/bin` ensures the overlay wins when present and the baseline takes over when it isn't.

**Rationale**:

- The PATH-precedence approach is dead-simple to reason about: an upgraded tool just becomes a same-named binary earlier in PATH.
- Bind mounts give operators a host-side `ls`/`cat`/`du -sh` inspection surface — Constitution Principle II ("Plain Files Where Humans Read State") is honored without effort.
- "Reset" is `rm -rf $ASDD_HOME/_state/tools/<project>/<tool>/` from the host — no docker subcommand, no confusion.
- An empty overlay falls through to baseline automatically — first-start has no "seed the volume" race condition (which the derived-image and copy-on-first-start approaches both have).

**Alternatives considered**:

- **Derived images per project** (commit each project's tool changes into a new image tag). Rejected: image management is heavy, image registry hygiene becomes the operator's problem, hard to inspect from the host, and image rebuild for the *baseline* image becomes a coordination problem with per-project derived tags.
- **Single shared docker volume** for tools across all projects. Rejected by FR-017 clarification: per-project is mandatory.
- **Per-project docker named volume** (instead of host bind mount). Rejected: less host-inspectable; backup story is worse; `du` on a named volume is awkward from the operator's terminal.
- **Copy-on-first-start from baseline into overlay**. Rejected: adds a first-start cost, introduces a subtle "did the copy run?" failure mode, and is unnecessary once PATH order does the job.

**Verification needs**:

- **VERIFY** that an empty `~/.asdd-tools/bin/` directory does not cause shells to error or print warnings when `PATH` includes it. (POSIX shells tolerate non-existent PATH entries silently, but it's worth a smoke test.)
- **VERIFY** that `npm install -g --prefix=/home/asdd/.asdd-tools/<tool>` writes the expected layout that the wrapper expects.

---

## R2. Install-method drivers

**Decision**: Three drivers cover today's tool set. Each implements a uniform Python interface in `asdd/tools.py`.

| Tool | Method | Source URL | Install layout in overlay |
|---|---|---|---|
| `claude` | `npm-global` | `https://registry.npmjs.org/@anthropic-ai/claude-code` | `~/.asdd-tools/<tool>/lib/node_modules/@anthropic-ai/claude-code/` + symlink at `~/.asdd-tools/bin/claude` |
| `gh` | `github-release` | `https://api.github.com/repos/cli/cli/releases/latest` (asset: `gh_<ver>_linux_<arch>.tar.gz`) | `~/.asdd-tools/<tool>/<ver>/` + symlink at `~/.asdd-tools/bin/gh` |
| `uv` | `astral-install` (script-based) | `https://astral.sh/uv/install.sh` with `UV_INSTALL_DIR` env | `~/.asdd-tools/<tool>/<ver>/` + symlink at `~/.asdd-tools/bin/uv` |

**Driver interface** (Python):

```python
class ToolDriver(Protocol):
    name: str                          # registry key ("claude", "gh", "uv")
    def installed_version(self, root: Path) -> str | None: ...
    def latest_version(self, *, timeout: float) -> str | None: ...
    def install(self, root: Path, version: str | None) -> str: ...   # returns the actually-installed version
    def uninstall(self, root: Path, version: str) -> None: ...
```

`root` is the per-tool subdirectory under the overlay (`~/.asdd-tools/<tool>/`). `version=None` means "latest". The driver is responsible for staging the install at `<root>/incoming/<ver>/`, then atomically renaming to `<root>/versions/<ver>/`. The CLI orchestrator updates the `bin/<name>` symlink last.

**Rationale**:

- The Protocol shape is small enough that adding a fourth tool is a < 100-line change with a unit test.
- All drivers are *additive* — they never modify a previously installed version. This keeps rollback trivial (re-point the symlink).
- Reusing per-tool subdirectories means each tool's storage layout can match the upstream's expectations (npm needs `lib/node_modules/...`; tarball tools just put a binary).

**Alternatives considered**:

- **Single uniform install layout** for all tools (every tool gets `<root>/<ver>/bin/<binary>`). Rejected: requires rewriting paths inside extracted archives, complicates npm-global (its `node_modules` layout matters to dependencies).
- **Reuse the upstream installers' default paths** (e.g., trust `npm install -g` to do everything). Rejected: we need the per-project isolation, and we need to be able to retain prior versions for rollback — both require us to control the layout.

**Verification needs**:

- **VERIFY** GitHub Releases rate limit for unauthenticated callers (60/hour/IP) is sufficient at the operator's scale (≤ 10 version checks per session start, ~5 sessions per day). It is.
- **VERIFY** the astral installer's `UV_INSTALL_DIR` flag still places `uv` directly in that dir.

---

## R3. Upstream version-check protocol

**Decision**: Per-driver `latest_version()` makes one HTTPS call to a public registry endpoint with a hard timeout. On failure (timeout, non-200, parse error), the driver returns `None`; callers render `?` in the versions table and skip banner emission for that tool. No retries within a single check — the operator will see "could not check" instead of waiting.

| Driver | Endpoint | Parse |
|---|---|---|
| `npm-global` | `GET https://registry.npmjs.org/-/package/<name>/dist-tags` | JSON: `{"latest": "<ver>"}` |
| `github-release` | `GET https://api.github.com/repos/<owner>/<repo>/releases/latest` | JSON: `{"tag_name": "v<ver>"}` (strip leading `v`) |
| `astral-install` | Same as `github-release` against `astral-sh/uv` | Same |

Timeouts: 2 s connect, 2 s read. Concurrency: when the version command checks multiple tools, the calls run in a `concurrent.futures.ThreadPoolExecutor(max_workers=8)` pool so total wall-clock stays bounded.

**Rationale**:

- The npm `/-/package/<name>/dist-tags` endpoint is ~50 bytes — much faster than the full `/<pkg>/latest` document.
- A 2 s budget per tool keeps the worst-case session-start banner under 4 s in the typical 2-tools-stale case, and `asdd versions` under 3 s total via parallelism (SC-006).
- The "could not check" degradation matches the spec's offline edge case.

**Alternatives considered**:

- **Background pre-fetch with cached "latest"**. Rejected: introduces a cache invalidation surface ("how stale is my notion of latest?") for marginal latency gain.
- **Subscribe to upstream announcement RSS/Atom feeds**. Rejected: complexity vs. payoff at one-operator scale.

**Verification needs**:

- **VERIFY** the npm `dist-tags` endpoint is stable + documented (it is; standard npm registry API).

---

## R4. `--reload` semantics for running Claude

**Decision**: When `asdd upgrade claude <project> --reload` runs and a persistent session is active for `<project>`:

1. The new `claude` is installed to the overlay (same as the no-`--reload` path).
2. The asdd CLI sends `tmux kill-window -t asdd:0` to the container — this terminates the running `claude` process cleanly.
3. The `asdd-session` outer-role supervisor sees the tmux session end, returns, and the container exits.
4. The launchd babysitter restarts the container.
5. The container's PATH now resolves `claude` to the overlay binary.
6. The inner-role of `asdd-session` runs `claude --continue --remote-control --name "$NAME"` — the conversation resumes in the new binary.

The whole flow takes ~2–5 seconds. The operator's claude.ai/mobile view briefly shows the session as offline, then reconnects.

**Rationale**:

- This reuses the existing supervisor restart path — no new code in `asdd-session`. The supervisor was already designed (spec 010) to handle "claude crashes, relaunch with `--continue`."
- `--continue` preserves conversation history (claude's responsibility, not ours).
- Without `--reload`, the install is purely a file operation — zero process disturbance, FR-002 satisfied trivially.

**Alternatives considered**:

- **In-place SIGHUP to the running claude**. Rejected: claude doesn't document a reload signal; relying on undocumented behavior is fragile.
- **Spawn a side-by-side claude in a second tmux window**. Rejected: confuses claude.ai's remote-control identity (two `claude --remote-control --name X` processes).
- **Refuse `--reload` if a persistent session is running**. Rejected: this is exactly the case the flag exists for.

**Verification needs**:

- **VERIFY** that `tmux kill-window` cleanly returns the supervisor (i.e., causes `tmux has-session` to return false) in the existing `asdd-session` script. Looking at the script: yes — the outer `while tmux has-session` loop exits when the session ends.

---

## R5. Concurrency safety

**Decision**: Per-(project, tool) file lock via `fcntl.flock` at `$ASDD_HOME/_state/tools/<project>/<tool>/.lock`. Held for the duration of an upgrade or rollback. Concurrent attempts get an immediate clear error: "upgrade for <tool> in <project> already in progress; try again in a moment."

**Rationale**:

- `fcntl.flock` is the standard POSIX advisory-lock primitive; it's host-side (not container-side) so it naturally serializes operator commands.
- Lock granularity is per-(project, tool), not global — different tools in different projects don't block each other.
- The lock file is harmless if left over (next acquisition succeeds); no cleanup required.

**Alternatives considered**:

- **One global asdd lock**. Rejected: serializes unrelated operations needlessly.
- **In-container lock via flock on the overlay path**. Rejected: harder to debug from the host; opt for host-side flock so the operator can `ls -la .lock` if they're suspicious.

**Verification needs**: None — `fcntl.flock` is well-understood.

---

## R6. Failure rollback at install time

**Decision**: Two-step install with atomic activation.

1. Driver installs the new version under `<root>/incoming/<ver>/`. May take seconds/minutes; arbitrary failure here leaves only `<root>/incoming/<ver>/` partial — harmless because nothing else references it.
2. CLI orchestrator atomically renames `<root>/incoming/<ver>/` to `<root>/versions/<ver>/` (single `rename(2)` syscall).
3. CLI orchestrator atomically replaces the `<overlay>/bin/<name>` symlink to point at the new version's binary (`symlink(2)` + `rename(2)` dance via `ln -sfn` semantics).
4. Manifest is updated last (the manifest is informational; the file system layout is the source of truth).

A failure at step 1 or 2 leaves the previous version still pointed at. A failure between steps 2 and 3 leaves both versions on disk but the symlink unchanged — the next upgrade's step 1 will overwrite `incoming/`, no harm. A failure at step 3 (vanishingly unlikely — it's a single rename) leaves the system in a partial state; the manifest writer detects this on next read and prints a diagnostic.

**Rationale**:

- Atomic file-system primitives (`rename(2)`, `symlink(2)`) give us per-step atomicity without a transaction manager.
- The two-step staging means the prior version is always intact during install (FR-009).

**Alternatives considered**:

- **Single-step install that overwrites in place**. Rejected: violates FR-009 (failed upgrade must leave the prior version intact).
- **Reference-counted version directories**. Rejected: unnecessary at the per-tool retention cap of 2.

**Verification needs**: None — atomic-rename is POSIX-standard.

---

## R7. Where Dockerfile changes land

**Decision**: `docker/Dockerfile.project` gets three changes:

1. Replace `RUN npm install -g @anthropic-ai/claude-code` (line 63) with an install that targets the baseline prefix:
   ```dockerfile
   RUN mkdir -p /opt/asdd-baseline \
       && npm install -g --prefix=/opt/asdd-baseline @anthropic-ai/claude-code
   ```
2. Similarly relocate `gh` and `uv` installs to `/opt/asdd-baseline/bin/`.
3. After the user-creation block (line 76+), set the user's PATH to put the overlay first:
   ```dockerfile
   ENV PATH="/home/asdd/.asdd-tools/bin:/opt/asdd-baseline/bin:/usr/local/bin:/usr/bin:/bin"
   ```
4. Write a baseline-version snapshot file at build time:
   ```dockerfile
   RUN /opt/asdd-baseline/bin/claude --version | awk '{print $1}' > /opt/asdd-baseline/versions/claude && \
       /opt/asdd-baseline/bin/gh --version | head -n1 | awk '{print $3}' > /opt/asdd-baseline/versions/gh && \
       /opt/asdd-baseline/bin/uv --version | awk '{print $2}' > /opt/asdd-baseline/versions/uv
   ```

The baseline snapshot lets `asdd versions` answer "what does the image baseline ship?" without re-running each tool's `--version` (faster). It's also what's consulted when the overlay is empty.

**Rationale**:

- All install paths move user-owned by virtue of `/opt/asdd-baseline/`; no root-owned files in `/usr/local/lib/node_modules/`.
- The overlay path doesn't need to exist in the image at all — `PATH` tolerates missing dirs.
- A snapshot file is more reliable than parsing `--version` output on every run.

**Verification needs**:

- **VERIFY** that npm with `--prefix` ignores the global `NPM_CONFIG_PREFIX` env var. (It does.)
- **VERIFY** that the user `asdd` is created before the PATH ENV line is set in the Dockerfile.

---

## R8. Banner content + placement

**Decision**: Banner is printed by the asdd CLI on the host (not in-container), AFTER the version check completes and BEFORE the `docker exec -it ... bash|claude|tmux attach` call. One line per stale tool, capped at 78 columns; uses ANSI dim+ember for the tool name + new version, default for the prose, ember for the command-to-run. Suppressed when:
- The check times out (no banner; spec edge case requires graceful offline handling).
- The tool is pinned and at the pinned version (no banner; the operator opted out of "you should upgrade").
- The tool is at the baseline version AND the baseline version is the latest (no banner; everything's current).

Sample (rendered):

```
⓿  claude 2.1.150 → 2.1.151 available — run `asdd upgrade claude dev` to apply
⓿  gh 2.94.0 → 2.95.0 available — run `asdd upgrade gh dev` to apply
```

**Rationale**:

- Printing host-side means the banner doesn't pollute the in-container session log and is trivially suppressible (operator can pipe asdd output through `| grep -v ⓿`).
- 78-column cap keeps it readable in 80-column terminals.
- The exact command-to-run is the banner's reason to exist (per the user's clarification answer); colorization makes it scannable.

**Alternatives considered**:

- **Banner inside the container's MOTD**. Rejected: MOTDs are skipped by `docker exec` (only shown on full login shells); also requires running banner generation inside the container, which is slower.
- **Use a separator like `===`**. Rejected: 78-column cap + simple prose is calmer.

**Verification needs**:

- **VERIFY** the ANSI escapes don't show through when the operator pipes asdd output to a file. (We'll honor `NO_COLOR` and `not sys.stdout.isatty()`.)

---

## R9. Migration story for existing containers

**Decision**: Existing containers (running before this feature lands) keep working without intervention. The first time the operator runs `asdd serve`, `asdd open`, or `asdd claude` against an existing project AFTER the new image is in place:

1. The old container is still running with the old image (no `claude` in overlay layout). The new asdd CLI detects the old image (image digest mismatch) and prints a one-line note: "container is using the previous image; recreate with `asdd stop <id> && asdd serve <id>` to enable in-container upgrades."
2. The operator can ignore the note indefinitely — old behavior continues.
3. When they recreate the container with the new image, the overlay is empty, the baseline is correct, and the new upgrade machinery is available.

**Rationale**:

- Zero forced migration. Operators in the middle of a long playtest don't have to restart anything.
- The note is non-blocking and self-documenting.

**Alternatives considered**:

- **Refuse to attach to old containers**. Rejected: hostile to operators with in-flight work.
- **Silently auto-recreate the container**. Rejected: violates "don't break anything" — recreating drops the running Claude.

**Verification needs**:

- **VERIFY** Docker exposes the image digest of a running container via `docker inspect`. (It does: `.Image` is the digest.)

---

## R10. Performance budgets

**Decision**:

| Operation | Target | Mechanism |
|---|---|---|
| `asdd versions <project>` end-to-end | < 3 s wall-clock with warm registry | Parallel version checks; per-tool 2s timeout. |
| Session-start banner (`asdd open` / `asdd claude` / `asdd serve`) before attach | < 2 s | Parallel checks; results cached for 5 minutes per `(tool, project)` so back-to-back sessions don't repay. |
| `asdd upgrade <tool> <project>` (no `--reload`) | < 30 s for npm-global; < 15 s for tarball-based | Single round-trip + stream install. |
| Session-start banner when offline | < 200 ms (just the cache miss notice) | Bypass version check on connect timeout. |

**Cache**: a small JSON file at `$ASDD_HOME/_state/tools/.version-cache.json` records `(tool, latest, checked_at)` tuples; entries older than 5 minutes are ignored. The cache is shared across projects (it's about *upstream* versions, not per-project state).

**Rationale**: SC-001 says 30s for the upgrade; SC-006 says the versions report fits "one terminal screen" — both implied bounded latency. The 5-minute cache is a low-magic number that keeps the banner snappy without making the freshness story confusing.

---

## R11. Out of scope (deferred)

These were considered and explicitly punted:

- **Tool downgrades to arbitrary historical versions** (only the last two are retained). If the operator needs an older version, they pin to it; if it's older than the retained set, they reinstall manually.
- **Auto-discovery of tools not in the registry**. The system handles its declared registry; an operator who installs random tools by hand doesn't get them tracked.
- **Cross-host coordination**. Per Assumptions, single Mac.
- **Authenticated upstream reads** (for higher rate limits). Out of scope at the current scale; revisit if GitHub API rate-limiting becomes a problem.
- **Tool removal** (e.g., `asdd remove claude <project>`). Use `asdd reset-tools claude <project>` to clear the overlay; baseline takes over.

---

## Decisions summary

| # | Decision |
|---|---|
| R1 | Two-layer PATH-ordered install (baseline + overlay). Bind-mounted overlay per project. |
| R2 | Three driver interfaces (`npm-global`, `github-release`, `astral-install`) covering claude/gh/uv. |
| R3 | Public-registry version probes with 2s timeout; parallel; degrade gracefully. |
| R4 | `--reload` flag bounces the persistent claude via tmux kill + supervisor restart with `--continue`. |
| R5 | Per-(project, tool) `flock` for concurrency safety. |
| R6 | Two-step install: `incoming/` → atomic rename to `versions/` → atomic symlink swap. |
| R7 | Dockerfile.project rewrites baseline installs to `/opt/asdd-baseline/`; overlay-first PATH. |
| R8 | Host-side one-line banner, ≤ 78 cols, suppressed on pin/current/timeout. |
| R9 | Old-image containers keep working; gentle recreate note. |
| R10 | < 3s versions report, < 2s banner, < 30s upgrade. 5-min upstream version cache. |
| R11 | Downgrade-to-arbitrary, auto-discover, multi-host, authenticated reads → out of scope. |
