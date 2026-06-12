# Implementation Plan: Per-project Claude state isolation under the shared auth store

**Branch**: `003-claude-state-isolation` | **Date**: 2026-06-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-claude-state-isolation/spec.md`

## Summary

Spec 009 currently bind-mounts the entire `_state/claude-auth/claude/` directory onto `~/.claude/` in every project container, sharing not only credentials but every per-project artifact Claude Code writes (transcripts, auto-memory, todos, shell-snapshots). Compounded by a constant `IN_CONTAINER_WORKDIR=/asdd_home`, this collapses every project's per-project state into a single shared pool.

The fix preserves spec 009's shared-credential model and adds a per-project state subtree alongside it. Container mounts become:

1. `_state/claude-auth/claude.json` → `~/.claude.json` (shared, file bind — unchanged)
2. `_state/claude-auth/per-project/<project_id>/` → `~/.claude/` (per-project, directory bind — new)
3. `_state/claude-auth/claude/.credentials.json` → `~/.claude/.credentials.json` (shared, file bind, overlaid on top of #2 — new)

`auth_mounts()` gains a `project_id` parameter; callers without one (the throwaway login container) get only the shared credential mounts. `ensure_mountable` is extended to materialise the per-project subtree and the shared `.credentials.json` placeholder. `auth.clear` recursively removes both the shared store and every per-project subtree. The existing project-lifecycle removal path gains a per-project state cleanup step. A first-run notice surfaces when the legacy mixed-state directory is detected.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: PyYAML, jsonschema, click (the only three permitted by CLAUDE.md invariant). Docker as the runtime substrate; subprocess-driven.

**Storage**: Filesystem under `$ASDD_HOME/_state/`. Docker bind mounts (file and directory). No database, no IPC.

**Testing**: pytest 8.x; 106 existing unit tests; integration tests gated on `docker` availability via existing `skipif` markers in `tests/integration/`.

**Target Platform**: Linux container running as user `asdd` (uid 1000) on macOS or Linux host. Per CLAUDE.md, deploy target is macOS via pipx; dev happens inside this devcontainer.

**Project Type**: CLI + per-project Docker container manager.

**Performance Goals**: Container start latency must not regress measurably. The new per-project subtree materialisation is a single `mkdir -p` + `chmod 0700` on the host — negligible.

**Constraints**:

- No new dependencies (3-dep CLAUDE.md invariant).
- Spec 009 invariants preserved: credential store stays under `$ASDD_HOME`; subscription auth is the default for all modes; `0700/0600` perms.
- Spec 010 invariants preserved: no inbound port; supervisor stays host-side launchd; persistent session sees its own transcript history across restarts.
- `IN_CONTAINER_WORKDIR=/asdd_home` and `IN_CONTAINER_USER_HOME=/home/asdd` are held constant.

**Scale/Scope**: Single operator, single host, tens to low-hundreds of projects realistically. Per-project state directories grow at the rate Claude Code writes transcripts and snapshots — bounded by Claude Code's own retention policies, not asdd's.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Rationale |
|-----------|--------|-----------|
| I. Spec-Driven Development | ✅ | This feature is itself executing the speckit pipeline. |
| II. Plain Files for Human State | ✅ | The new per-project subtree is plain filesystem state with a stable layout under `$ASDD_HOME/_state/claude-auth/per-project/<project_id>/`. Inspectable by `ls` and `cat`. |
| III. Single Writer per File | ⚠️→✅ | Each project's per-project subtree has exactly one writer (that project's container at a time). The shared `.credentials.json` is written by whichever Claude session is refreshing tokens. The pre-existing race (multiple sessions refreshing simultaneously) is unchanged by this feature, not introduced by it. Acceptable. |
| IV. Container-Portable Runtime | ✅ | Pure Docker bind-mount changes. No new host-OS-specific dependency. |
| V. Secret Hygiene | ✅ | Credentials remain under `_state/claude-auth/` with `0700/0600` perms. Per-project subtrees are also `0700`. Nothing decrypted to project workspaces. |
| VI. Default Branch Protection | ✅ | Work on feature branch; no destructive ops on `main`. |

No violations. No Complexity Tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/003-claude-state-isolation/
├── plan.md              # This file
├── research.md          # Phase 0 output — three technical decisions
├── data-model.md        # Phase 1 output — store layout and entity contracts
├── quickstart.md        # Phase 1 output — operator-facing validation runbook
├── contracts/           # Phase 1 output — auth_mounts + lifecycle contracts
│   ├── auth-mounts.md
│   └── project-lifecycle.md
└── tasks.md             # /speckit-tasks output (not created here)
```

### Source Code (repository root)

```text
asdd/
├── auth.py                  # MODIFY: extend ensure_mountable; add per_project_dir(); update clear()
├── project_container.py     # MODIFY: auth_mounts(asdd_home, project_id); _compose_mounts threading
├── lifecycle.py             # MODIFY: project-removal path also removes _state/claude-auth/per-project/<id>/
├── bootstrap.py             # MODIFY: emit one-time migration notice when legacy mixed state detected
└── contracts/
    └── (no schema changes — auth_mounts and lifecycle are internal contracts)

tests/
├── unit/
│   ├── test_auth.py                    # ADD cases: per_project_dir, ensure_mountable creates placeholder, clear() removes per-project trees
│   └── test_project_container.py       # ADD cases: auth_mounts(home, None) → 1 mount; auth_mounts(home, "p") → 3 mounts in order
└── integration/
    └── test_state_isolation.py         # NEW: docker-gated; two-container leakage test (FR-001) and shared-cred test (FR-002)
```

**Structure Decision**: Conventional Python package layout already in place (CLAUDE.md). Three production files touched (`auth.py`, `project_container.py`, `lifecycle.py`), one operator-message change (`bootstrap.py`), two unit-test files extended, one new integration test added. No new top-level directories.

## Complexity Tracking

> No violations. No entries.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| _none_    |            |                                     |
