# Implementation Plan: Container shell vs. Claude entry points, container-aware prompt, preinstalled `gh`

**Branch**: `001-container-shell-and-gh` | **Date**: 2026-06-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-container-shell-and-gh/spec.md`.

## Summary

Split the operator's "enter the container" surface into two explicit commands and make the in-container shell self-identifying:

- `asdd open <project>` keeps its name but is unambiguously a **shell**. It already calls `attach_shell` in `asdd/project_container.py`; this feature codifies that contract in tests, help text, and docs so no future change re-introduces an auto-Claude.
- `asdd claude <project>` is a **new** Click command that re-uses the existing interactive-container start path and replaces `attach_shell` with an `attach_claude` helper that runs `docker exec -it <name> claude`. It honors the same auth gate (`_require_login`) and the same persistent-session re-attach (`is_persistent_running` → `attach_session`) that `cmd_open` uses today.
- The in-container shell prompt is made project-aware via an `ASDD_PROJECT_ID` env var set by `start_container` (and a tiny `/etc/profile.d/asdd-prompt.sh` baked into the image), so any bash spawned in the container — `asdd open`, manual `docker exec`, or a sub-shell — shows the project name.
- The project image's existing `gh 2.92.0` pin is bumped to the latest stable, and the `gh --version` check is added to the existing image smoke test so a future regression is caught at CI time, not by an operator hitting "command not found."

Code lives entirely in this repo: `asdd/bootstrap.py` (Click command), `asdd/project_container.py` (new helper), `docker/Dockerfile.project` (new profile.d snippet + `gh` bump), plus tests under `tests/unit/`. No new packages; no schema changes.

## Technical Context

**Language/Version**: Python 3.12 (matches `python:3.12-slim` base in `docker/Dockerfile.project` and the existing CLI venv).

**Primary Dependencies**: existing only — `click` for the CLI, `PyYAML` and `jsonschema` for asdd's existing surfaces (per `pyproject.toml`). No new Python deps. The container image gains `gh` (already present, version bump only) and one `/etc/profile.d/` snippet.

**Storage**: N/A. No new on-disk state. The existing project registry (`$ASDD_HOME/_state/registry.json` etc.) is read-only here.

**Testing**: `pytest` (existing). Unit tests around `cmd_open`, `cmd_claude` (new), and `attach_claude` (new) using the existing `monkeypatch`-on-subprocess pattern in `tests/unit/test_project_container.py` and `tests/unit/test_persistent_session.py`. No new test framework. Docker-dependent integration tests skip cleanly when Docker isn't available (existing convention in `tests/integration/`).

**Target Platform**: Operator's host (macOS or Linux) drives a Docker daemon that runs the project image. The image targets `linux/amd64` and `linux/arm64`. No new platform constraints.

**Project Type**: CLI + per-project container image. Existing single-project Python layout under `asdd/`.

**Performance Goals**: per-spec SC-001/SC-002 — `asdd open` and `asdd claude` complete cold-start in under 5 seconds against an already-built image. The change adds at most one env-var insertion and one `docker exec` invocation; no measurable overhead.

**Constraints**: must not break the duplicate-open guard, the persistent-session re-attach, or the auth-mount layout from spec 009. Must keep `pyproject.toml` deps at exactly the three currently allowed (`PyYAML`, `jsonschema`, `click`). Must keep the image build reproducible (pinned `gh` version, not `latest`).

**Scale/Scope**: pre-1.0 operator-facing tool. ~14 unit tests added/modified, ~50 lines of CLI code, ~10 lines of Dockerfile, one new ~5-line profile.d snippet, one ~15-line `attach_claude` helper.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Applicability | Status | Notes |
|---|---|---|---|
| I. Spec-Driven Development | Yes — this is a new feature. | PASS | Driven by `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement`, all under `specs/001-container-shell-and-gh/`. |
| II. Plain Files Where Humans Read State | Yes — touching docs/`USER_GUIDE.md`, `CLAUDE.md`, project skeleton README. | PASS | All edits are to existing Markdown surfaces. No binary state added. |
| III. Single Writer per File | Yes — touching CLI source, Dockerfile, tests. | PASS | Single feature branch; one writer (the implementer) per file at a time. |
| IV. Container-Portable Runtime | Yes — Dockerfile changes, no host-side daemons. | PASS | No host-OS-specific facilities used. The prompt mechanism is bash + an env var; `gh` is an arch-aware tarball install (already the pattern). |
| V. Secret Hygiene | Touched indirectly — `asdd claude` re-uses the existing subscription auth path. | PASS | No new secrets. Subscription auth still loads from `_state/claude-auth/`; no decrypted material on disk. `gh` auth tokens land in the operator's `~/.config/gh` which is per-container ephemeral (the same lifecycle as today's manual install). |
| VI. Default Branch Protection | Yes — final merge targets `main` via PR. | PASS | Plain merge commit via `gh pr merge`; no force-push, no history rewrite. |

**Gates: ALL PASS at initial check.** No complexity-tracking entries needed.

## Project Structure

### Documentation (this feature)

```text
specs/001-container-shell-and-gh/
├── spec.md                  # Feature spec (already written)
├── plan.md                  # This file
├── research.md              # Phase 0 — Click command, exec-vs-CMD, profile.d, gh version
├── data-model.md            # Phase 1 — entities (commands, env vars, image artifacts)
├── quickstart.md            # Phase 1 — operator runbook for the two new commands
├── contracts/
│   ├── cli-asdd-open.md     # Revised `asdd open` contract
│   ├── cli-asdd-claude.md   # New `asdd claude` contract
│   └── container-image.md   # Image-level contract: PS1, env vars, `gh` presence
└── checklists/
    └── requirements.md      # Spec quality checklist (already written)
```

### Source Code (repository root)

```text
/asdd_home/
├── asdd/
│   ├── bootstrap.py           # CHANGE: new `cli.command("claude")`; revise `open` help text;
│   │                          # add cmd_claude(); preserve cmd_open() shape but assert "no claude".
│   ├── project_container.py   # CHANGE: add attach_claude(); add ASDD_PROJECT_ID to extra_env
│   │                          # in start_container() so the in-container shell can pick it up.
│   └── lifecycle.py           # No change (no public-state changes).
├── docker/
│   ├── Dockerfile.project     # CHANGE: bump GH_VERSION pin; COPY new profile.d snippet.
│   └── files/
│       └── asdd-prompt.sh     # NEW: tiny /etc/profile.d/ script that reads ASDD_PROJECT_ID
│                              # and prepends "(project) " to PS1 if interactive.
├── tests/
│   ├── unit/
│   │   ├── test_bootstrap_cli.py        # NEW or extend existing: cover `asdd claude` Click wiring,
│   │   │                                # cmd_claude success/auth-error/persistent-attach paths.
│   │   ├── test_project_container.py    # EXTEND: cover attach_claude() subprocess call, and
│   │   │                                # ASDD_PROJECT_ID being passed through extra_env.
│   │   └── test_persistent_session.py   # EXTEND: cover `asdd claude` attaching to persistent
│   │                                    # session (mirrors existing `test_open_attaches_when_persistent`).
│   └── integration/
│       └── test_image_smoke.py          # NEW or extend: assert `gh --version` exit 0 in the
│                                        # built image; assert profile.d prompt sets PS1.
├── README.md                   # CHANGE: split the "interactive mode" sentence into open vs claude.
├── USER_GUIDE.md               # CHANGE: same split; update the worked example.
├── CLAUDE.md                   # CHANGE: orientation note around the two commands.
└── project_skeleton/CLAUDE.md  # CHANGE: same orientation note inside scaffolded projects.
```

**Structure Decision**: keep the existing single-project Python layout. No new packages, no new top-level directories. The Dockerfile-side helper script lives in `docker/files/` alongside the existing `asdd-run-job.sh` and `asdd-session.sh`.

## Complexity Tracking

> No constitution violations. No entries needed.

## Phase 0 Re-Check

After writing `research.md` and confirming there are no `NEEDS CLARIFICATION` items left in Technical Context (none were present at the initial draft — all decisions had a defensible default), the Constitution Check above re-evaluated **unchanged**. Still PASS across all six principles.

## Phase 1 Re-Check

After writing `data-model.md`, `contracts/`, and `quickstart.md`, the design deltas are:

- One new CLI command (`asdd claude`), one revised contract for `asdd open`, one new container-image contract.
- One new helper (`attach_claude`) parallel to `attach_shell`.
- One new env var (`ASDD_PROJECT_ID`) plumbed through `start_container`.
- One new `/etc/profile.d/` snippet (bash).
- One pinned `gh` version bump in the Dockerfile.
- Zero new third-party dependencies (client or container). Zero schema changes. Zero new persistent state.

Re-evaluated Constitution Check: **still PASS** on all six principles. No complexity table needed.

## Notes for `/speckit-tasks`

Sequence tasks so that the user-facing change is testable end-to-end as early as possible:

1. **Container image contract first** (`attach_claude` helper + env var plumbing + Dockerfile bump + profile.d snippet). Tests around `start_container` and `attach_claude`. Blocks the CLI surface tests because the image is the runtime substrate.
2. **`asdd claude` CLI surface** (Click command in `bootstrap.py`; `cmd_claude()` in `bootstrap.py`). Tests against the CLI's Click runner plus unit tests on `cmd_claude` paths (no Docker required; uses the same `monkeypatch.setattr(project_container, …)` style as existing tests).
3. **`asdd open` contract codification** (no behavior change; help text revision + new unit test that asserts `attach_shell` is called and `attach_claude` is not). Keeps the test surface symmetric.
4. **`PS1` prompt smoke test** (integration test that runs the image with `docker run --rm -e ASDD_PROJECT_ID=foo asdd/project:latest bash -lc 'echo "$PS1"'` and asserts `foo` is present in the output).
5. **`gh` smoke test** (integration test in the image: `gh --version` exits 0 and prints a version).
6. **Documentation refresh** (`USER_GUIDE.md`, `CLAUDE.md`, `README.md`, `project_skeleton/CLAUDE.md`). Single commit covering all four files; keeps the message-history coherent.
