---
description: "Task list for 004-serve-mobile-pairing"
---

# Tasks: Reliable mobile-app pairing and reconnect for `asdd serve`

**Input**: Design documents from `/specs/004-serve-mobile-pairing/`

**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓

**Tests**: REQUESTED. The spec carries explicit Independent-Test sections per user story and the contracts each carry a unit-test contract. Test tasks are included.

**Organization**: tasks grouped by user story. US2 (reconnect) and US3 (restart) have verification-only phases — no implementation tasks unless Phase 0's R3 hypothesis (Claude auto-reconnects on its own) fails empirically during US1 validation, in which case those phases gain a single fallback task each.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: different files OR additive non-overlapping edits to the same file; safe to run concurrently with other `[P]` tasks once their prerequisites are done
- **[Story]**: maps to spec.md user stories (US1, US2, US3) — Setup, Foundational, Cross-Cutting, Polish have no Story label
- File paths are repo-root relative

## Path conventions

Existing layout from `plan.md`: Python source under `asdd/`, container scripts under `docker/files/`, tests under `tests/{unit,integration}/`. No new top-level directories.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: feature is additive; no scaffolding needed.

_No tasks._

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: pairing-state detection helpers that every story consumes (the inspection surface for US1, the assertion mechanism for US2/US3 integration tests).

**⚠️ CRITICAL**: no user story tests can run without these.

- [X] T001 [P] Add `PairingState` literal type and module constant `PAIRING_FRESH_WINDOW_SECONDS = 60` near the top of `asdd/project_container.py` (after the existing `IN_CONTAINER_*` constants block). Type: `Literal["paired", "unpaired", "reconnecting", "n/a"]`.
- [X] T002 [P] Add helper `_read_session_files(project_id: str) -> list[dict]` to `asdd/project_container.py` that does one `docker exec <container> sh -c 'cat ~/.claude/sessions/*.json 2>/dev/null || true'`, parses each line as JSON, returns the list (empty when no container, no session, or unparseable). Pure passthrough; no filtering.
- [X] T003 Add helper `pairing_state(project_id: str, *, now: float | None = None) -> PairingState` to `asdd/project_container.py` (after T002). Logic per `data-model.md` derivation table — returns `"n/a"` when no persistent container is running; otherwise reads session files via T002, filters to `cwd == IN_CONTAINER_WORKDIR and kind == "interactive"`, derives state from `bridgeSessionId` presence and `updatedAt` freshness vs `now` (default `time.time() * 1000`). Inject `now` for testability.
- [X] T004 [P] Add `_pairing_state_unit_tests` to `tests/unit/test_project_container.py`: six cases per `contracts/asdd-ps.md` unit-test contract — no container, no session file, empty bridgeSessionId, recent paired, stale `>60s` reconnecting, no-network-call assertion. Mock `subprocess.run` to fake docker output.

**Checkpoint**: pairing state can be derived for any project. US1's ps column has its data source.

---

## Phase 3: User Story 1 — Serve pairs with mobile on startup (Priority: P1) 🎯 MVP

**Goal**: deliver the bug fix the user reported. `asdd serve <id>` causes the session to appear in the Claude mobile app within 30 seconds (SC-001) with no further command, and `asdd ps` shows the new `PAIRED` column.

**Independent Test**: spec acceptance scenarios for US1 (`spec.md`); quickstart section 1.

### Tests for User Story 1

- [X] T005 [P] [US1] Add `tests/unit/test_session_script.py` — bash-level smoke that asserts the outer role of `docker/files/asdd-session.sh` (a) runs `tmux new-session -d` exactly once, (b) follows it with a backgrounded `tmux attach -d` (`&` + `disown`), (c) redirects the idle attach's stdin to `/dev/null`. Use a stubbed `tmux` binary on `PATH` that just logs argv, run the outer role end-to-end with `ASDD_PROJECT_ID=t`, kill after 2s.
- [X] T006 [P] [US1] Extend `tests/unit/test_bootstrap_cli.py` (or new `tests/unit/test_bootstrap_ps.py` if cleaner) with cases that mock `project_container.pairing_state` and assert `cmd_ps` returns rows whose `paired` field carries the helper's verdict (`"paired"`, `"unpaired"`, `"reconnecting"`, `"n/a"`) — one case per state.

### Implementation for User Story 1

- [X] T007 [US1] Modify `docker/files/asdd-session.sh` outer role per `contracts/asdd-session.md`: after `tmux new-session -d -s "$SESSION" "$0 --inner"`, add `tmux attach -t "$SESSION" -d </dev/null >/dev/null 2>&1 &` then `disown`, then keep the existing `while tmux has-session` loop. Brief comment refers to "spec 004 R2 — idle client keeps a live terminal so claude --remote-control completes its bridge handshake".
- [X] T008 [US1] Modify `asdd/bootstrap.py:cmd_ps` to call `project_container.pairing_state(project_id)` for every active row and include the result as `paired` in returned dicts. Sort/format unchanged.
- [X] T009 [US1] Modify the click-CLI `ps` subcommand renderer (search `asdd/bootstrap.py` for the `cmd_ps` print path) to display the new `PAIRED` column between `STATE` and `CONTAINER` per `contracts/asdd-ps.md`. JSON output is automatic (cmd_ps already returns dicts).

### Integration test for User Story 1

- [X] T010 [P] [US1] Create `tests/integration/test_serve_pairing.py` — docker-gated, gated by `pytest.mark.docker`. Skipped where no docker. Cases:
  - `test_serve_session_pairs_within_30s` — `asdd serve <id>` with `ASDD_SESSION_STUB=` unset (real claude is required), poll `pairing_state` every 2s up to 30s, assert eventually `"paired"`. Skipped (xfail) when running without a real Anthropic login.
  - `test_ps_shows_paired_column_for_running_serve` — start a serve, run `cmd_ps`, assert returned dict has the new `paired` key with one of the four values. This case works with `ASDD_SESSION_STUB=1` (stubbed inner role): `paired` reads `"unpaired"` because no real claude → no session JSON. Still proves the wiring.

**Checkpoint**: P1 MVP delivered. The bug is fixed; `asdd ps` exposes pairing state. Validate against US1's acceptance scenarios before moving on. **If T007's intervention A does not produce a `bridgeSessionId` within 30s of serve startup in real validation, escalate to intervention B (`tmux send-keys` to inject `/remote-control`) — single-line change in the same file. Intervention C (`script(1)` wrapper) is the last resort.**

---

## Phase 4: User Story 2 — Reconnect after transient outage (Priority: P1)

**Goal**: verify Claude's own bridge-reconnect behaviour suffices for SC-002 (≥95% / 60s). No code change unless empirics fail.

**Independent Test**: quickstart section 3 + the integration test below.

### Integration test for User Story 2

- [X] T011 [P] [US2] Extend `tests/integration/test_serve_pairing.py` with `test_serve_session_recovers_after_network_loss` — docker-gated. Block the container's outbound network with `docker network disconnect`, wait 90s, reattach, poll `pairing_state` for up to 60s, assert eventually `"paired"`. Marked `xfail` if no live login.

### Conditional implementation for User Story 2

- [ ] T012 [US2] **Conditional — only if T011 fails consistently against a live login.** Implement R3 fallback: a small in-container watchdog inside `asdd-session.sh` that polls `~/.claude/sessions/*.json` once per minute and, if `bridgeSessionId` has gone missing while the container is up and reachable, `tmux send-keys` `/remote-control\n` once to re-trigger pairing. Re-test T011. Document the trigger in `asdd-session.sh` comments. Do NOT do this preemptively.

**Checkpoint**: SC-002 met. Either by Claude's own reconnect (preferred — T012 stays unchecked) or by the lightweight watchdog. The watchdog never restarts the container (FR-012).

---

## Phase 5: User Story 3 — Pairing survives container restart (Priority: P2)

**Goal**: verify the existing launchd-driven restart path also re-pairs (SC-003).

**Independent Test**: quickstart section 4 + the integration test below.

### Integration test for User Story 3

- [X] T013 [P] [US3] Extend `tests/integration/test_serve_pairing.py` with `test_serve_session_repairs_after_container_restart` — start a serve, `docker stop` the container, wait for the launchd babysitter to relaunch it (poll `is_running` for up to 30s), then poll `pairing_state` for up to 60s, assert eventually `"paired"`. Skip cleanly when no launchd (Linux dev) — use a manual `start_existing` call to simulate the relaunch.

**Checkpoint**: post-restart pairing exercise covered. Same `pairing_state` machinery; no new asdd code is required if T007 holds.

---

## Phase 6: Cross-cutting — `asdd logout` tears down running serves

**Purpose**: deliver clarification Q2 / FR-006 / edge case. Independent of US1-3 from a code-touch standpoint; sequencing-wise it should land after Phase 3 to keep diffs cohesive.

### Tests for the logout flow

- [X] T014 [P] Add `tests/unit/test_bootstrap_logout.py` with the five cases in `contracts/asdd-logout.md` unit-test contract:
  - no running serves → clears store, returns success
  - one running serve → `supervisor.uninstall` + `stop_container` + `remove_container` called in that order, then `auth.clear`
  - two running serves → both stopped, then clear
  - serve that fails to stop → `auth.clear` NOT called, exit non-zero
  - failure error message names the failing project

### Implementation for the logout flow

- [X] T015 Modify `asdd/bootstrap.py:cmd_logout` to enumerate running serve sessions (iterate registry rows with `is_persistent_running`), tear each down (`supervisor.uninstall`, `stop_container`, `remove_container`), collect failures into a list, refuse to call `auth.clear` if any failures, print the failure message from `contracts/asdd-logout.md`, return non-zero. Successful run still calls `auth.clear(asdd_home)` and returns the existing success path.

**Checkpoint**: `asdd logout` is safe in the presence of running serves.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T016 [P] Update `CLAUDE.md` spec 010 invariant phrasing (currently: `"remote-control" is local attach, never an inbound listener`). Replace with a clearer two-clause statement: (a) "no inbound port on the container — pairing is outbound HTTPS"; (b) "the persistent container runs ONE Claude process; `asdd attach` and `asdd claude` join it via tmux, never spawn a second claude". Keep the same table row position.
- [X] T017 [P] Update `USER_GUIDE.md` `asdd serve` section to describe the new `asdd ps` `PAIRED` column, the four states (paired / unpaired / reconnecting / n/a), and the recovery semantics ("walk away, pairing reconnects on its own").
- [X] T018 [P] Update `USER_GUIDE.md` `asdd logout` section with one sentence: "running serve sessions are stopped first; logout refuses if any cannot be stopped cleanly".
- [X] T019 [P] Run `make lint`; fix any new findings in changed files only (do not refactor pre-existing).
- [X] T020 Run `make test`; confirm all pre-existing pass + new unit tests pass + integration tests skip cleanly without docker.
- [ ] T021 Walk through `quickstart.md` sections 1–6 manually on the Mac deploy target with a phone in hand. Document any deviation. Section 1 (mobile-visible within 30s), section 3 (reconnect after Wi-Fi off), section 5 (logout cleanliness) are the must-pass ones.

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 2 (Foundational)**: T001 → T002 → T003 → T004. T001 and T002 are `[P]` only relative to each other (different concerns, same file); landing them as separate commits is fine. T003 strictly depends on T002. T004 depends on T003.
- **Phase 3 (US1)**: depends on Phase 2 complete.
  - T005 (bash smoke) and T006 (ps mock tests) can be written `[P]` before implementation.
  - T007 (`asdd-session.sh`), T008 (`cmd_ps` data path), T009 (`cmd_ps` rendering) can land independently after their respective tests pass.
  - T010 (docker-gated integration) depends on T007 + T008 + T009 having landed.
- **Phase 4 (US2)**: depends on Phase 3 working in real validation.
  - T011 is the verification step. T012 is conditional and runs only if T011 fails.
- **Phase 5 (US3)**: depends on Phase 3 working.
  - T013 is verification only; no implementation dependency.
- **Phase 6 (Logout)**: independent of Phases 3-5 at the code level; sequence after Phase 3 to keep diff cohesive.
- **Phase 7 (Polish)**: depends on all desired US/cross-cutting work being landed.

### Within each phase

- Tests authored before implementation per the test-first convention (see `tasks-template.md` notes).
- For Phase 3: T007 (`asdd-session.sh`) and T008 (`cmd_ps` data) can land in either order — they don't share files. T009 (rendering) depends on T008 since it consumes the new field.

### Parallel opportunities

- Phase 2: T001 + T002 are additive edits to `asdd/project_container.py` — parallel commits OK.
- Phase 3 tests: T005, T006, T010 are independent files.
- Phase 3 impl: T007 vs (T008 + T009) — different files, parallel-safe.
- Phase 6: T014 vs T015 — test-first; can be written `[P]` then T015 lands implementation.
- Phase 7: T016 + T017 + T018 + T019 — each touches different files, fully parallelizable.

---

## Parallel Example: User Story 1

```bash
# Phase 2 complete, now in parallel for US1 tests:
Task: "T005 — bash smoke for asdd-session.sh in tests/unit/test_session_script.py"
Task: "T006 — cmd_ps mock tests in tests/unit/test_bootstrap_ps.py"
Task: "T010 — integration test scaffold in tests/integration/test_serve_pairing.py"

# Then implementation, also parallel-safe:
Task: "T007 — outer-role idle attach in docker/files/asdd-session.sh"
Task: "T008 — cmd_ps reads pairing_state in asdd/bootstrap.py"
# T009 follows T008 (same file region):
Task: "T009 — PAIRED column in ps renderer"
```

---

## Implementation Strategy

### MVP first (US1 + the logout cross-cutting)

1. Phase 2 (Foundational): land `asdd/project_container.py` helpers + unit tests.
2. Phase 3 (US1): land `asdd-session.sh` change + `cmd_ps` PAIRED column + tests.
3. Phase 6 (Logout): land cmd_logout teardown — small, isolated, satisfies the edge case.
4. **STOP AND VALIDATE on Mac** with quickstart section 1 + section 5. If T007 fails to produce paired sessions, fall to intervention B (single-line change to T007), revalidate.
5. Ship MVP. The reported bug is fixed.

### Incremental delivery

1. MVP (above) → operator runs serve on their Mac, sees mobile pairing, no manual step.
2. Phase 4 (US2 reconnect verification) → ride along on next operator validation pass; only adds code if T011 fails.
3. Phase 5 (US3 restart verification) → same as above.
4. Phase 7 polish → final.

### Risks

- **R2 intervention A doesn't fix pairing**: documented fallbacks B and C; each is a small change to T007. The MVP is not blocked on one being right first time.
- **Claude doesn't auto-reconnect (R3)**: T012 watchdog is the contingency.
- **Mobile-end verification is manual**: SC-001/SC-002/SC-003's 95%-over-20-trials targets are operator-validated on Mac, not CI. Quickstart documents the trial procedure.

---

## Notes

- `[P]` tasks are non-overlapping edits; same file is OK if the edits are additive and non-conflicting (e.g., separate helper functions added to one Python module).
- Tests for the slack scenarios (network down, container restart) are docker-gated and skip cleanly without docker — matches existing `tests/integration/` conventions.
- The "validate-on-Mac" pattern from CLAUDE.md applies: T021 is on the operator, not CI.
- No file in this feature uses emojis in code or comments (per CLAUDE.md communication preferences).
