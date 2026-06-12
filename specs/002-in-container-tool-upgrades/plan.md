# Implementation Plan: Convenient & Secure In-Container Tool Upgrades

**Branch**: `002-in-container-tool-upgrades` | **Date**: 2026-06-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-in-container-tool-upgrades/spec.md`

## Summary

Restructure how operator-facing tools (`claude`, `gh`, `uv`, future additions) live inside per-project containers so they can be upgraded without rebuilding the image, without losing the persistent Claude session, and without elevating to root permanently — while still surviving container recreation and image rebuilds.

**The mechanism**: a two-layer install model inside each container.

1. **Baseline layer** (`/opt/asdd-baseline/bin/`) — installed during image build, owned by root, never changes after build. Acts as the floor: every container always has a working set of tools even if everything else is wiped.
2. **Project overlay layer** (`/home/asdd/.asdd-tools/`) — bind-mounted from `$ASDD_HOME/_state/tools/<project_id>/` on the host. Owned by the `asdd` user. Each project has its own independent slice. Operator upgrades land here. Empty overlay = fall through to baseline.

`PATH` puts overlay first, baseline second, system third — so an upgraded `claude` shadows the baseline `claude` cleanly.

**The surface**: new asdd subcommands `versions`, `upgrade`, `rollback`, `pin`, `unpin`, `reset-tools` — all running as the `asdd` user inside the running container via `docker exec`. No host-side `docker` incantations required. No permanent root elevation; only the upgrade step itself runs under the overlay layer's owner (the `asdd` user — who already owns the bind-mount path).

**The signaling**: every `asdd open` / `asdd claude` / `asdd serve` does a quick (≤2s per tool, soft-timeout) upstream version check and prints a one-line banner per stale tool before attaching — naming the exact `asdd upgrade …` command to run. Nothing upgrades silently.

## Technical Context

**Language/Version**: Python 3.12 (asdd is a pip-installed CLI; matches the existing codebase's `pyproject.toml` setting).

**Primary Dependencies**:

- Existing: `click` for CLI, `pyyaml` for config, `sopsy`/`age` for secrets (per Constitution V).
- Added: none required. Upstream version checks use `urllib.request` from the standard library with `socket.setdefaulttimeout` — no new HTTP client dependency.

**Storage**:

- Per-project tool overlay: `$ASDD_HOME/_state/tools/<project_id>/` on the host, bind-mounted to `/home/asdd/.asdd-tools/` in the container. Plain files; constitution-aligned (II).
- Per-project tool metadata (pins, version history, rollback targets): plain JSON at `$ASDD_HOME/_state/tools/<project_id>/<tool>/manifest.json`.

**Testing**: `pytest` (matches existing `tests/unit/` and `tests/integration/`). Unit tests run with mocked `subprocess.run` and mocked `urllib.request.urlopen`. Integration tests run against a real Docker container (gated on Docker availability).

**Target Platform**: macOS host (operator's Mac), Linux containers (Debian 12 slim base, per current `Dockerfile.project`).

**Project Type**: CLI tool with container-side helpers. Single-project repository layout (no front-end).

**Performance Goals**:

- `asdd versions <project>`: full report rendered in ≤ 3 seconds end-to-end with a warm registry (one network round-trip per tool, in parallel where possible). Soft-timeout 2s per tool; report shows "could not check" on timeout, never blocks longer.
- `asdd upgrade claude <project>` against a running session: ≤ 30s end-to-end (SC-001), of which network + npm install dominates.
- Session-start banner check: ≤ 2 s total before attach (SC-009 readability + low-latency expectation).

**Constraints**:

- The persistent Claude session MUST NOT be terminated by any upgrade flow that does not explicitly opt in via `--reload` (FR-002, SC-008).
- The container MUST NOT run as root permanently (FR-010). Any root operation is limited to image-build time.
- The overlay layer MUST be inspectable + backup-friendly from the host (Constitution II + III). The host-side dir is plain files; the operator can copy, tar, or version-control it.
- The upgrade flow MUST work without internet for installed-version reporting; only the "is anything newer available?" check requires internet, and degrades gracefully (FR-007 + edge case in spec).

**Scale/Scope**:

- Tools managed at launch: 3 (`claude`, `gh`, `uv`).
- Tools the architecture supports: any tool installable via npm-global, GitHub releases, astral installer, or a documented "fetch-and-place" entry — at most ~20 tools per project before the table no longer fits one terminal screen (SC-006).
- Concurrent projects per operator: typically 2–5; the architecture has no per-host cap.
- Per-project disk footprint: ~50–300 MB depending on tool set + rollback retention (cap = 2 prior versions).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Applicability | Status | Notes |
|---|---|---|---|
| I. Spec-Driven Development | This feature is itself spec-driven; the path is intact (`spec.md → clarifications → plan.md → research.md → data-model.md → contracts/ → quickstart.md → tasks.md → implementation`). | PASS | Following the workflow. |
| II. Plain Files Where Humans Read State | The persistence layer is plain JSON manifests + bind-mounted binary trees, all under `$ASDD_HOME/_state/tools/`. Inspectable with `ls`, `cat`, `jq` from the host. | PASS | No SQLite, no binary-only state. |
| III. Single Writer per File | Each project's overlay path has a single writer (the asdd CLI invoked by the operator). Manifests are written by exactly one process; a file lock prevents concurrent upgrades for the same `(project, tool)`. | PASS | Lock file at `$ASDD_HOME/_state/tools/<project>/<tool>/.lock`. |
| IV. Container-Portable Runtime | No new host-OS-specific dependency. The launchd babysitter (already required by spec 010) remains the only host-specific surface; this feature doesn't add another. | PASS | Banner check runs inside the container, fired from asdd's exec-based attach helpers. |
| V. Secret Hygiene | Tool upgrades don't introduce new secrets. The npm/gh/registry calls are public; no credentials are needed for reads. (Authenticated upstream reads would be future work — out of scope.) | PASS | No `.enc.yml` changes. |
| VI. Default Branch Protection | Implementation lands on `002-in-container-tool-upgrades` branch and merges via PR to `main`. No force-push. | PASS | Standard PR flow. |

**Gates: ALL PASS at initial check.** No complexity-tracking entries needed.

## Project Structure

### Documentation (this feature)

```text
specs/002-in-container-tool-upgrades/
├── spec.md                 # Feature spec (with Clarifications)
├── plan.md                 # This file
├── research.md             # Phase 0 — install-method patterns, version-check shape, layering choice
├── data-model.md           # Phase 1 — tool registry, manifest, lock, pin entities
├── quickstart.md           # Phase 1 — "upgrade claude in 30s" recipe
├── contracts/
│   ├── cli-commands.md           # asdd upgrade / versions / rollback / pin / unpin / reset-tools
│   ├── overlay-layout.md         # On-disk layout of $ASDD_HOME/_state/tools/<project>/
│   ├── manifest-schema.json      # JSON Schema for per-tool manifest.json
│   ├── tool-registry.md          # How a tool plugs into the system (the abstract interface)
│   └── banner-format.md          # Stale-tool banner shape + placement rules
├── checklists/
│   └── requirements.md     # Quality gate from /speckit-specify
└── tasks.md                # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
asdd/                                # existing Python package
├── bootstrap.py                     # CHANGE: add cmd_upgrade, cmd_rollback, cmd_pin,
│                                    #         cmd_unpin, cmd_versions, cmd_reset_tools;
│                                    #         wire banner into cmd_open / cmd_claude / cmd_serve
├── project_container.py             # CHANGE: new helpers for exec-as-asdd-user upgrade calls;
│                                    #         mount the overlay bind-mount on container start;
│                                    #         banner pre-attach hook
├── tools.py                         # NEW: tool registry + per-method install drivers
│                                    #      (npm-global, github-release, astral-install)
├── tool_manifest.py                 # NEW: read/write per-tool manifest.json under the overlay
├── version_check.py                 # NEW: upstream "is newer available?" with timeout
│                                    #      + per-method version probes
└── banner.py                        # NEW: one-line banner builder + render

docker/
├── Dockerfile.project               # CHANGE: install claude+gh+uv to /opt/asdd-baseline;
│                                    #         set PATH to overlay-first;
│                                    #         seed entrypoint (none needed — empty overlay
│                                    #         simply falls through to baseline via PATH)
└── files/
    └── asdd-baseline-versions.json  # NEW: snapshot of baseline tool versions for the image,
                                     #      written at build time; the in-container banner
                                     #      reads this so it can compare baseline vs latest.

tests/
├── unit/
│   ├── test_tools.py                # NEW: registry + each install method's drivers (mocked)
│   ├── test_tool_manifest.py        # NEW: read/write/migrate of manifest.json
│   ├── test_version_check.py        # NEW: registry probes, timeout, offline degradation
│   ├── test_banner.py               # NEW: banner copy + length + placement
│   └── test_bootstrap_upgrade.py    # NEW: cmd_upgrade / cmd_rollback / cmd_versions
└── integration/
    └── test_upgrade_e2e.py          # NEW: gated on Docker; upgrade claude in a real container

USER_GUIDE.md                        # CHANGE: new "Keep your tools current" section
CLAUDE.md                            # CHANGE: SPECKIT-START block points to this plan
```

**Structure Decision**: Existing single-project layout extended. No new top-level package. All new code lives inside the existing `asdd/` package and `docker/` directory.

## Phase 0 — Research (see `research.md`)

Investigated:
1. **Install-method patterns** for the three current tools (npm-global, GitHub releases, astral installer). Each becomes a "method driver" in `tools.py`.
2. **Overlay vs. derived-image layering**. Picked PATH-ordered overlay (operator overlay → baseline → system) over docker-commit-style derived images because: (a) keeps each container layer ephemeral, (b) bind mounts let operators inspect/back up upgrades trivially, (c) survives image rebuilds without per-project image management.
3. **Version-check protocol** per tool. npm: `GET https://registry.npmjs.org/<pkg>/latest`. GitHub: `GET https://api.github.com/repos/<owner>/<repo>/releases/latest`. astral/uv: `GET https://api.github.com/repos/astral-sh/uv/releases/latest`. All with 2 s connect+read timeout. Authenticated requests deferred (rate limits acceptable at one-operator scale).
4. **In-place reload semantics for the persistent Claude**. Picked `--reload` flag triggering tmux kill-window → supervisor relaunch with `claude --continue`. Conversation resumes; brief reconnect (~2s).
5. **Concurrency safety**. Per-tool file lock at `$ASDD_HOME/_state/tools/<project>/<tool>/.lock` using `fcntl.flock`. Concurrent attempts get a clear error, never race.
6. **Failure rollback at install time**. Stage new binary at `<tool>/incoming/`; atomically rename to `<tool>/current/` on success. Failure leaves prior `current/` in place untouched.

## Phase 1 — Design & Contracts

Deliverables:

- `data-model.md` — entities `ManagedTool`, `Manifest`, `UpgradePlan`, `Pin`, `RollbackTarget`, plus state diagram for the manifest's `state` field.
- `contracts/cli-commands.md` — exact subcommand grammar, args, exit codes for each new asdd command.
- `contracts/overlay-layout.md` — on-disk layout under `$ASDD_HOME/_state/tools/<project>/` with examples.
- `contracts/manifest-schema.json` — JSON schema for the per-tool manifest.
- `contracts/tool-registry.md` — the abstract install-method interface and how the three concrete drivers (`npm-global`, `github-release`, `astral-install`) implement it.
- `contracts/banner-format.md` — banner string template, length cap, ordering rules, suppression rules.
- `quickstart.md` — "upgrade claude in 30s" end-to-end recipe.
- `CLAUDE.md` SPECKIT-START block updated to point to this plan.

## Phase 1 Re-Check

After writing the design docs, no constitution gate changes. Specifically:
- The overlay path lives entirely under `$ASDD_HOME` (Principle V — secrets stay there too, well-separated).
- All file writes go through the asdd CLI as the sole writer (Principle III — single writer per file).
- Bind mount remains the operator-inspectable surface (Principle II — plain files where humans read state).

## Notes for `/speckit-tasks`

Sequence the implementation as:

1. **Foundation** (no user story yet) — `tools.py` registry shape, `tool_manifest.py` read/write + tests, `version_check.py` + tests, file-lock helper + tests. Blocks everything below.
2. **US1 (Upgrade in running container, P1 MVP)** — Dockerfile changes for baseline + overlay path; `cmd_upgrade` end-to-end for `claude` via `npm-global` driver; integration test against a real container.
3. **US2 (Survive container recreation, P1)** — overlay bind-mount wiring in `project_container.start_container`; entrypoint seeding rules; verify the overlay survives `asdd stop` + `asdd serve`.
4. **US3 (Versions table, P2)** — `cmd_versions` with parallel version checks; banner integration in `cmd_open`/`cmd_claude`/`cmd_serve`.
5. **US4 (Pinning, P3)** — `cmd_pin`/`cmd_unpin`; pin enforcement in `cmd_upgrade` (single + bulk); pin display in `cmd_versions`.
6. **Rollback + reset** — `cmd_rollback` (single tool, most recent retained); `cmd_reset_tools` for clearing the overlay.
7. **Polish** — second + third tool drivers (`gh` via `github-release`, `uv` via `astral-install`); user guide; CLAUDE.md updates.
8. **Production validation** — Docker integration tests against the new image; performance check (banner ≤ 2s, upgrade ≤ 30s).

## Complexity Tracking

No constitution violations. Empty.
