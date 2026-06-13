# Implementation Plan: Long, Naturally-Scrollable Session History

**Branch**: `005-scrollback-history` | **Date**: 2026-06-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-scrollback-history/spec.md`

## Summary

Interactive Claude sessions (`asdd claude` / `asdd attach` / `asdd open`) are joined
through a tmux session that holds one long-lived `claude` process alive (spec 004/010).
Because the operator's terminal talks to tmux rather than to Claude directly, tmux's
defaults govern scrolling — and tmux ships with a short scrollback (`history-limit 2000`)
and mouse off. That is why history "stops" and why scrolling needs Shift gymnastics.

The fix is a small, declarative tmux configuration baked into the project image:
raise `history-limit` to a local-terminal-like depth and turn `mouse on` (with copy-mode
clipboard niceties). tmux reads the config at server start — i.e. when
`asdd-session.sh` runs `tmux new-session` — so the held pane is created with the large
history, and every later `tmux attach` (all three entry points) inherits the same
server-global mouse setting and the same pane history. No code path, command surface, or
network posture changes.

## Technical Context

**Language/Version**: tmux configuration (declarative); Bash for `asdd-session.sh`; Python 3.12 for the CLI/tests. No new Python code required.

**Primary Dependencies**: tmux (already installed in `docker/Dockerfile.project`). No new Python or system packages.

**Storage**: N/A — scrollback is an in-memory ring buffer per tmux pane, bounded by `history-limit`.

**Testing**: pytest. Unit: assert the image ships the tmux config and that it sets the required options (mirrors `tests/unit/test_session_script.py` style). Integration (docker-gated, skips cleanly): assert a built image's tmux server reports the configured `history-limit` and `mouse` values.

**Target Platform**: Linux container (`asdd/project:latest`), attached from a macOS operator terminal via `docker exec -it … tmux attach`.

**Project Type**: CLI + container image (single project, conventional Python layout).

**Performance Goals**: No measurable runtime impact on the live session. Memory cost of a deeper history buffer is bounded (~tens of MB worst case at 50000 lines × pane width) and only grows as output is produced.

**Constraints**: Must not open any inbound port; must not alter the mobile/web remote-control view; must preserve detach (Ctrl-b d) and text copy-out; must apply automatically with no per-session operator step. `history-limit` must be set in config read *before* the session pane is created (it does not retroactively resize existing panes).

**Scale/Scope**: One config file + one Dockerfile `COPY` line + tests + a USER_GUIDE note. Retained depth target: 50000 lines (comfortably satisfies SC-001's ≥2000-line read-back).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Spec-Driven Development**: Following the `/speckit-*` artifact chain under `specs/005-scrollback-history/`. PASS.
- **II. Plain Files Where Humans Read State**: The change is a human-readable tmux config (text) baked into the image. PASS.
- **III. Single Writer per File**: New file `docker/files/asdd-tmux.conf` has a single writer (the image build). No shared-file contention. PASS.
- **IV. Container-Portable Runtime**: The fix lives entirely inside the container image; it depends on tmux, not on any host-OS facility. No host coupling introduced. PASS.
- **V. Secret Hygiene**: Untouched — no credentials involved. PASS.
- **VI. Default Branch Protection**: Work proceeds on `005-scrollback-history`; no destructive git ops. PASS.

**Invariant review** (CLAUDE.md): No regression. Image tag, container prefix, schema/skeleton paths, the three-Python-deps rule (tmux is a system package, not a Python dep), subscription-auth default, per-project state isolation, host-side-launchd-only supervision / no inbound port, and one-claude-per-container all remain as-is. The mouse/history settings are server-global within a single tmux session and do not spawn a second client or process.

**Result**: PASS — no violations, Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/005-scrollback-history/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (configuration parameters)
├── quickstart.md        # Phase 1 output (validation guide)
├── contracts/
│   └── tmux-session.md  # Phase 1 output (session-behaviour contract)
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
docker/
├── Dockerfile.project        # add COPY of asdd-tmux.conf → /etc/tmux.conf
└── files/
    ├── asdd-session.sh       # unchanged (tmux reads /etc/tmux.conf at server start)
    └── asdd-tmux.conf        # NEW — history-limit + mouse + copy-mode settings

tests/
├── unit/
│   └── test_tmux_config.py           # NEW — config presence + required options
└── integration/
    └── test_scrollback_history.py    # NEW — docker-gated; assert live server options

USER_GUIDE.md                  # note: scrolling/copy behaviour in attached sessions
```

**Structure Decision**: Single-project layout, unchanged. The feature adds one container
config asset (`docker/files/asdd-tmux.conf`) wired in via a single `COPY` in
`docker/Dockerfile.project`, plus tests and a short operator-doc note. `asdd-session.sh`
is intentionally left untouched: placing the config at `/etc/tmux.conf` means tmux loads
it automatically when the server starts, so no script edit is needed.

## Complexity Tracking

> No constitution violations — section intentionally empty.
