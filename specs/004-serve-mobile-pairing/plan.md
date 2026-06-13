# Implementation Plan: Reliable mobile-app pairing and reconnect for `asdd serve`

**Branch**: `004-serve-mobile-pairing` | **Date**: 2026-06-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-serve-mobile-pairing/spec.md`

## Summary

`asdd-session.sh` (the PID 1 inside a serve container) starts tmux **detached** with `tmux new-session -d` and runs `claude --remote-control` inside the pane. The `--remote-control` flag exists in Claude Code 2.1.175 — so it isn't the wrong flag. The empirical evidence is that the same flag, in the same code path, registers the session with the mobile pairing service **only after** a terminal client is attached to tmux (the operator's `asdd attach`/`asdd claude` reaching it). Without an attached client at startup, pairing does not complete.

The fix is to make pairing complete without requiring a human-attached terminal. Phase 0 research nails down which of several plausible mechanisms is actually load-bearing (TTY presence at startup vs interactive `stdin` vs in-session slash-command trigger) and picks the smallest reliable intervention.

The clarifications in the spec lock the architecture: one long-running Claude process per project (`tmux` continues to hold it), reconnect after network loss is owned by that in-container process (no container restart on transient pairing loss), pairing status surfaces in `asdd ps`, and `asdd logout` tears down running serves first. Everything else from spec 010 (launchd babysitter, no inbound port, `claude --continue` resume across container restarts) is preserved.

## Technical Context

**Language/Version**: Python 3.12 for the asdd CLI; bash for `docker/files/asdd-session.sh`.

**Primary Dependencies**: PyYAML, jsonschema, click (3-dep CLAUDE.md invariant — no additions). Inside the container: Claude Code 2.1.175 (`claude`), tmux. macOS host: launchd.

**Storage**: filesystem under `$ASDD_HOME/_state/`. The pairing-token state (if any persists outside Claude's own `~/.claude/` tree) lives wherever Claude Code puts it; asdd does not introduce a new store.

**Testing**: pytest (existing unit suite); integration tests gated on docker availability. Mobile-end verification cannot be automated against an Anthropic-owned service; the quickstart provides a manual checklist for that leg.

**Target Platform**: Linux container running as user `asdd` on macOS host. Deploy target is macOS via pipx (CLAUDE.md dev/deploy split).

**Project Type**: CLI + per-project Docker container manager.

**Performance Goals**: pairing visible on mobile within 30 seconds of `asdd serve` return (SC-001); reconnect within 60 seconds of route restoration on ≥95% of trials (SC-002); same bound for post-restart pairing (SC-003).

**Constraints**:

- No new Python dependencies.
- Preserve spec 010 invariants: launchd babysitter, no inbound port, persistent container survives detach.
- Preserve spec 003 invariants: per-project Claude state isolated, credentials shared.
- Preserve spec 009 invariants: subscription auth default for all modes.
- `IN_CONTAINER_WORKDIR=/asdd_home` unchanged.

**Scale/Scope**: tens of projects per host realistically; one operator, one Anthropic account per host.

**Open question (resolved in Phase 0)**: NEEDS CLARIFICATION — exact mechanism by which `claude --remote-control` completes mobile-pairing registration on startup vs. on attach. Working hypothesis: it requires a TTY-attached tmux client present when pairing kicks off; current `asdd-session.sh` launches tmux detached, leaving the pairing handshake without a terminal. Phase 0 confirms or replaces this hypothesis with the actual mechanism and picks the minimal intervention.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Rationale |
|-----------|--------|-----------|
| I. Spec-Driven Development | ✅ | This feature is itself executing the speckit pipeline. |
| II. Plain Files for Human State | ✅ | Pairing status surfaces through `asdd ps` (already a plain-text command). No new opaque state file. |
| III. Single Writer per File | ✅ | One serve container per project; that one container is the writer for `~/.claude/` per-project state (spec 003). Pairing reconnects are internal to that process. |
| IV. Container-Portable Runtime | ✅ | Pairing is outbound HTTPS from inside the container. No new host-OS-specific dependency. |
| V. Secret Hygiene | ✅ | No new credential store. Pairing reuses the shared spec 009 credential surface. |
| VI. Default Branch Protection | ✅ | Work on feature branch. |

**Spec 010 invariant compatibility**: the CLAUDE.md line "remote-control is local attach, never an inbound listener" was always meant as "no inbound port"; pairing is outbound HTTPS, so the no-listener guarantee still holds. The phrasing is misleading in light of this feature and will be refined in Phase 6 polish — that is a docs change, not an invariant change.

No violations. No Complexity Tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/004-serve-mobile-pairing/
├── plan.md              # This file
├── research.md          # Phase 0 — pairing-mechanism diagnosis + 4 decisions
├── data-model.md        # Phase 1 — paired-session entity + state machine
├── quickstart.md        # Phase 1 — operator-facing validation runbook
├── contracts/           # Phase 1 — operator-visible contracts that change
│   ├── asdd-ps.md
│   ├── asdd-session.md
│   └── asdd-logout.md
└── tasks.md             # /speckit-tasks output (not created here)
```

### Source Code (repository root)

```text
asdd/
├── bootstrap.py             # MODIFY: cmd_logout tears down running serves; cmd_ps gains the paired column
├── project_container.py     # MODIFY: pairing-status detection helpers; align attach_session/attach_claude with FR-011
└── ...

docker/files/
└── asdd-session.sh          # MODIFY: ensure --remote-control completes pairing without requiring a human terminal (mechanism per Phase 0)

tests/
├── unit/
│   ├── test_bootstrap_logout.py        # NEW or extend test_bootstrap_auth.py — logout tears down running serves
│   ├── test_project_container.py       # ADD: pairing-status helper tests
│   └── test_session_script.py          # NEW — bash-level smoke for asdd-session.sh outer/inner contract
└── integration/
    └── test_serve_pairing.py           # NEW — docker-gated: serve→ps shows paired; restart→re-paired
```

**Structure Decision**: Conventional layout. One bash file changes (`asdd-session.sh`), one Python file gains a small surface area (`project_container.py` — pairing helpers), one Python flow tightens (`cmd_logout`). New tests at the unit and integration level. No new top-level directories. The mobile-end of the verification stays manual (operator with phone) — automated end-to-end against Anthropic's pairing service is out of scope.

## Complexity Tracking

> No violations. No entries.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| _none_    |            |                                     |
