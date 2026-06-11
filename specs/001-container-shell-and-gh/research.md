# Phase 0 Research: Container shell vs. Claude entry points

**Feature**: 001-container-shell-and-gh
**Date**: 2026-06-11
**Status**: Decisions locked.

There are no `[NEEDS CLARIFICATION]` markers in the spec or in the plan's Technical Context. The items below are the design decisions whose alternatives needed to be considered explicitly before Phase 1.

## R1. How to introduce `asdd claude` without rewriting `cmd_open`

**Decision**: Add a new top-level Click command `asdd claude` in `asdd/bootstrap.py` whose handler `cmd_claude()` re-uses every piece of `cmd_open()` except the final attach step. `cmd_open()` calls `attach_shell()`; `cmd_claude()` calls a new `attach_claude()`. Both share `_require_login`, `is_persistent_running`/`attach_session`, `ensure_image_built`, `assert_not_running`, `start_container`, and `stop_container`.

**Rationale**:

- The two commands share 100% of pre-attach setup. Factoring the "open the container, run X inside, stop the container" path into a tiny internal helper would over-abstract for a feature that only spawns two callers; copy-paste of ~10 lines is clearer than a new abstraction.
- The persistent-session fast path (`is_persistent_running` → `attach_session`) is *already* what the operator wants from `asdd claude`: re-attach to the running tmux'd Claude rather than spawn a second one. Keeping the code path identical here means we inherit that contract for free.
- `attach_session` itself runs `tmux attach`, which lands the operator in the existing Claude session inside tmux — the right behavior for `asdd claude` when a persistent session exists. For `asdd open`, we instead want a clean shell, NOT to land in the tmux'd Claude. See R5 for that branch.

**Alternatives considered**:

- **Add `--claude` flag to `asdd open`.** Rejected: the spec explicitly asks for two separate commands. A flag couples the surfaces (anyone reading `asdd open --help` has to learn the flag) and runs against the user's stated mental model.
- **Refactor `cmd_open` into a generic `_attach_in_container(project_id, attach_fn)`.** Rejected as premature abstraction. Two callers do not need a strategy pattern. If a third caller (`asdd debug`, `asdd repl`) ever arrives, refactor then.

**Verification needs**: None — the function shapes already exist; the new code is parallel.

## R2. How to pass the project identifier into the in-container shell

**Decision**: Add `ASDD_PROJECT_ID=<project_id>` to the env vars `start_container` plumbs into the container at create time. Inside the image, a tiny `/etc/profile.d/asdd-prompt.sh` reads that variable and prepends `(<project>) ` to `PS1` if the shell is interactive.

**Rationale**:

- `start_container` already accepts an `extra_env` dict for project-secrets injection (per FR-014 in the file's docstring). Adding one more key is the lowest-overhead plumbing.
- `/etc/profile.d/*.sh` is sourced by login bash shells and by interactive non-login bash via `~/.bashrc` if the in-image bashrc sources it (the default Debian skeleton does this). This catches `docker exec -it bash -l` (asdd's current flow), manual `docker exec -it bash`, and sub-shells inside the container — exactly the three FR-008 cases.
- The mechanism is bash-only, which is fine because asdd containers run a single bash login shell as the user-facing entry. There is no zsh/fish surface to support today.
- The variable is set at container-create time, not at exec time, so any future `docker exec` against the same container automatically inherits it.

**Alternatives considered**:

- **Set `ASDD_PROJECT_ID` only in the `docker exec` for `asdd open`.** Rejected: spec FR-008 explicitly says the prompt must work for any shell entered via manual `docker exec` or a sub-shell, not just the asdd CLI-launched one. Container-level env is the only way to cover those.
- **Bake the project name into the image at build time.** Rejected: the image is shared across projects (single `asdd/project:latest`). Project name must be runtime-injected.
- **Write a file with the project name into the container's bind-mounted workspace and read it from `~/.bashrc`.** Rejected: file-based plumbing through a bind mount is more moving parts than an env var, and the file would survive past the container's lifetime if the operator copied the workspace.

**Verification needs**:

- **Confirm** Debian's default `~/.bashrc` for the in-container `asdd` user sources `/etc/profile.d/*.sh` for non-login interactive shells. (It does, via `/etc/bash.bashrc` which Debian's bashrc-skeleton sources by default.)
- **Confirm** the `useradd --create-home` in the Dockerfile preserves the Debian default `~/.bashrc`; if not, append a one-line source. (It does — `useradd` copies `/etc/skel`, which on `python:3.12-slim` includes the standard Debian `~/.bashrc`.)

## R3. PS1 format

**Decision**: prepend `(<project>) ` to whatever `PS1` is at the time `/etc/profile.d/asdd-prompt.sh` runs. The snippet does NOT overwrite the operator's prompt entirely — it composes around it.

**Rationale**:

- Matches the de facto convention used by Python venvs, conda envs, direnv, etc. — operators recognize "the parenthesized prefix means I'm inside something." Reuses an existing mental model rather than inventing a new one.
- Preserves any user-side customization of `PS1` later in the session: a subsequent `export PS1='\u@\h:\w$ '` deliberately wipes the prefix because the user chose to.
- The "if interactive" guard (`[[ $- == *i* ]]`) keeps the prefix out of non-interactive shells (asdd's dispatch mode, autonomous `claude --print`), so log output and result captures stay clean.

**Alternatives considered**:

- **Embed the project name as a colored badge in PS1.** Rejected: color escapes are terminal-dependent and risk wedging the prompt in old terminals. Parentheses are universal.
- **Replace `PS1` entirely with a fixed format.** Rejected: would fight operators who already have a preferred prompt. The spec's FR-009 explicitly says we must not prevent override.

**Verification needs**: None — bash `PS1` composition is standard.

## R4. `gh` version pin policy

**Decision**: bump the Dockerfile's `ARG GH_VERSION` from `2.92.0` to the latest stable release at implementation time (`2.94.0` as of 2026-06-10). Adopt a policy that the pin is bumped intentionally — at most once per asdd minor release — rather than chasing HEAD. Add a comment in the Dockerfile naming the release and date so future maintainers can see the cadence.

**Rationale**:

- The current pin is ~8 months old; spec SC-004 says `gh --version` MUST work, and a pin this old has accumulated CVE fixes worth taking.
- Keeping the pin explicit means we get reproducible builds (image rebuild in 6 months still produces the same image). A floating `latest` would silently move under us.
- One bump per asdd minor release is enough — `gh`'s public API is stable, and we don't depend on bleeding-edge features.

**Alternatives considered**:

- **Float to `latest`.** Rejected per Constitution Principle I (reproducible builds) and the spec edge case "version drift."
- **Pin to the current `2.92.0`.** Rejected: stale and SC-004 explicitly motivates bumping.
- **Install via apt instead of from the GitHub release tarball.** Rejected: Debian 12's repo `gh` lags upstream by months; we'd get the same staleness problem with less control.

**Verification needs**:

- **Verify** the release tarball naming scheme (`gh_<v>_linux_<arch>.tar.gz`) at the chosen version. Current scheme has been stable since `gh 1.0`.

## R5. Persistent-session interaction for `asdd open`

**Decision**: `asdd open` MUST refuse with a clear error when a persistent session is running for the project. The current code unconditionally calls `attach_session` (tmux attach to the running Claude) when `is_persistent_running` returns true — that behavior moves to `asdd claude` only. `asdd open` instead errors with a message pointing the operator at `asdd attach` or `asdd claude`.

**Rationale**:

- Today's `asdd open` returns `attach_session(project_id)` if persistent. Under the new contract that means "asdd open lands in Claude" exactly when a session is running, which is the very surprise we're removing.
- A bare error is preferable to "open a second shell inside the session container" because the session container is `--restart unless-stopped` and runs only `claude --remote-control` inside tmux; there isn't a meaningful shell to land in without breaking session invariants.
- `asdd attach` already exists and is the canonical "join the live session" path. The error message directs the operator there.

**Alternatives considered**:

- **Allow `asdd open` to docker-exec a fresh bash *into* the session container alongside tmux.** Rejected: complicates the session container's contract (it's currently single-process by design — `asdd-session.sh` running claude). Two-shells-in-one-container is a footgun.
- **Keep the silent re-attach to tmux/Claude on `asdd open`.** Rejected: directly contradicts the spec.

**Verification needs**: None — the change is in `cmd_open`, covered by a unit test.

## R6. `asdd claude` interaction with the persistent session

**Decision**: `asdd claude` re-attaches to the running persistent session via `attach_session` (tmux attach), exactly the way `cmd_open` does today. No new behavior for this case.

**Rationale**:

- Spec FR-006 says `asdd claude` MUST re-attach to a running persistent session — which is literally `attach_session`.
- This preserves the single-Claude invariant of the session container.

**Alternatives considered**:

- **Refuse `asdd claude` if persistent session is running, mirror `asdd attach`.** Rejected: the operator's intent is "drop me into Claude for this project"; re-attaching to the running one is the right answer.

**Verification needs**: None — reuses an existing code path.

## R7. Backwards compatibility for `asdd open` callers

**Decision**: treat `asdd open` semantic change as a breaking change for the platform's pre-1.0 phase. Document the change prominently in the user guide and CLAUDE.md. Do not provide a `--legacy` flag or a fallback that re-enables the old "auto-claude" path.

**Rationale**:

- The platform is pre-1.0 and operator-facing; we know of no automated callers.
- A `--legacy` flag would lock us into maintaining two interactive entry-point surfaces forever.
- Spec FR-013 covers the documentation update; that is the migration path.

**Alternatives considered**:

- **Print a one-time hint on `asdd open` that says "this used to start Claude; now use `asdd claude`."** Considered. Not necessary for an operator-only tool, and a deprecation notice that fires on a non-deprecated command (we want this to be the permanent behavior) is noise.

**Verification needs**: None.

## R8. Test strategy without spinning Docker

**Decision**: replicate the existing `test_persistent_session.py` style — `monkeypatch.setattr(project_container, "is_persistent_running", lambda _: True)` and friends — for the new `cmd_claude` paths. The image-level Dockerfile contracts (`gh --version`, PS1 prefix) are validated by the existing image-smoke pattern in `tests/integration/`, which skips cleanly when Docker is unavailable.

**Rationale**:

- The existing unit tests don't require Docker; they patch out the subprocess boundary. Reusing this pattern keeps the CI lightweight and aligns with the existing repo convention (per CLAUDE.md: "integration tests skip cleanly when docker isn't available").
- The image-level contracts are inherently runtime; an integration test that builds the image and runs `gh --version` is the cheapest honest verification.

**Alternatives considered**:

- **Spin a real container in every unit test.** Rejected: slow, flaky, requires Docker on the test runner.
- **No image smoke at all.** Rejected: that's exactly how the prompt or `gh` regression would slip through.

**Verification needs**: None — pattern is established in the existing tests.
