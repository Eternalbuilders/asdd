---

description: "Task list for Long, Naturally-Scrollable Session History"
---

# Tasks: Long, Naturally-Scrollable Session History

**Input**: Design documents from `/specs/005-scrollback-history/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/tmux-session.md, quickstart.md

**Tests**: Included — the plan (research R6) specifies a unit layer (`tests/unit/test_tmux_config.py`) and a docker-gated integration layer (`tests/integration/test_scrollback_history.py`). The repo invariant "tests pass before commit" applies.

**Organization**: Tasks are grouped by user story. Note the unusual shape of this feature: a single baked tmux config (`/etc/tmux.conf`) delivers the behaviour, so US1 and US2 each contribute **one directive** to the same shared file. The foundational phase wires the file into the image; each story phase adds its directive plus its verifying tests.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 / US2 / US3 from spec.md
- Exact file paths included.

## Path Conventions

Single project (this repo): container assets under `docker/`, tests under `tests/`, operator docs at repo root. No `src/` tree is involved — this is a container-image config change.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the config asset and wire it into the image build.

- [X] T001 Create `docker/files/asdd-tmux.conf` with a header comment explaining it is the baked global tmux config for operator-attached sessions (spec 005), read at tmux server start; leave directive lines to be added by the story phases. Mirror the file-mode convention of other `docker/files/*` assets (source 0600).
- [X] T002 Add a `COPY --chmod=0644 docker/files/asdd-tmux.conf /etc/tmux.conf` line to `docker/Dockerfile.project`, placed alongside the other `docker/files/*` COPY lines (near the `asdd-session.sh` / `asdd-prompt.sh` copies), with a one-line comment referencing spec 005.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the shared config baseline both user stories build on, and confirm tmux actually loads it.

**⚠️ CRITICAL**: US1 and US2 both edit `docker/files/asdd-tmux.conf` and depend on it being wired (T001–T002) and loadable.

- [X] T003 In `docker/files/asdd-tmux.conf` add the shared, story-neutral baseline `set -g mode-keys vi` (predictable copy-mode navigation; does not affect detach or prefix), per data-model.md.
- [X] T004 Create `tests/unit/test_tmux_config.py` with a shared fixture/helper that locates `docker/files/asdd-tmux.conf` and `docker/Dockerfile.project` (follow the `REPO_ROOT = Path(__file__).resolve().parents[2]` pattern from `tests/unit/test_session_script.py`), plus a test asserting the Dockerfile copies the config to `/etc/tmux.conf`.
- [X] T005 Create `tests/integration/test_scrollback_history.py` skeleton: a docker-availability guard that **skips cleanly** when docker is unavailable (match the pattern in `tests/integration/test_serve_pairing.py` / `test_image_smoke.py`), plus a helper that starts a tmux server inside a container using the baked `/etc/tmux.conf` and returns `tmux show-options -g <name>` output.

**Checkpoint**: Config file exists, is copied to `/etc/tmux.conf`, and test scaffolding is in place. Story directives can now be added.

---

## Phase 3: User Story 1 - Scroll back through a long session (Priority: P1) 🎯 MVP

**Goal**: An attached session retains a long scrollback so the operator can re-read output produced thousands of lines earlier.

**Independent Test**: On a built image, `tmux show-options -g history-limit` reports `50000`; in a live attached session the operator can scroll back ≥2000 lines (SC-001).

### Implementation for User Story 1

- [X] T006 [US1] Add `set -g history-limit 50000` to `docker/files/asdd-tmux.conf` (per data-model.md / contract C1; must be a global `set -g` so it is read before the held pane is created).
- [X] T007 [P] [US1] In `tests/unit/test_tmux_config.py` add a test asserting the config contains `set -g history-limit 50000`.
- [X] T008 [US1] In `tests/integration/test_scrollback_history.py` add a docker-gated test asserting the live server reports `history-limit 50000` (contract C1), using the helper from T005.

**Checkpoint**: Long-history behaviour is configured and verified independently of mouse scrolling.

---

## Phase 4: User Story 2 - Scroll with the mouse wheel, no modifier (Priority: P1)

**Goal**: Rolling the mouse wheel scrolls the session history directly, with no modifier key, like a local terminal.

**Independent Test**: On a built image, `tmux show-options -g mouse` reports `on`; in a live attached session a plain wheel-up gesture scrolls into history and wheel-down returns to live (SC-002, SC-003).

### Implementation for User Story 2

- [X] T009 [US2] Add `set -g mouse on` to `docker/files/asdd-tmux.conf` (contract C2). (Depends on T006 — same file; not parallel with US1's config edit.)
- [X] T010 [P] [US2] In `tests/unit/test_tmux_config.py` add a test asserting the config contains `set -g mouse on`.
- [X] T011 [US2] In `tests/integration/test_scrollback_history.py` add a docker-gated test asserting the live server reports `mouse on` (contract C2).

**Checkpoint**: Both P1 stories delivered — the config now provides long history AND modifier-free mouse scrolling.

---

## Phase 5: User Story 3 - Consistent behaviour across entry points (Priority: P2)

**Goal**: `asdd claude`, `asdd attach`, and `asdd open` observe identical history depth and mouse behaviour.

**Independent Test**: Attaching to the same session via each entry point shows the same `history-limit`/`mouse` and the same scroll feel (contract C7).

### Implementation for User Story 3

- [X] T012 [US3] Verify in code that all three entry points join the same single tmux session/pane (cross-check `asdd/project_container.py:attach_session` and the `cmd_claude` / `asdd open` paths in `asdd/bootstrap.py` against `docker/files/asdd-session.sh`); add a short note to `tests/integration/test_scrollback_history.py` (or assert via the existing helper) that the server-global `set -g` options are observed regardless of which attach path is used. No config change expected — this story is satisfied by the server-global settings from US1/US2.
- [X] T013 [US3] Add a brief "Scrolling & copy in attached sessions" note to `USER_GUIDE.md`: mouse-wheel scrolls history with no modifier; hold the terminal's bypass modifier (Option/Shift) to select text for the system clipboard; `Ctrl-b d` still detaches and leaves the session running. Reference behaviour C3–C7.

**Checkpoint**: Behaviour confirmed consistent across all join paths and documented for operators.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T014 Run `make test` and confirm the new unit tests pass and integration tests skip cleanly where docker is unavailable (repo invariant: tests pass before commit).
- [ ] T015 Rebuild `asdd/project:latest` and execute the `quickstart.md` validation (sections B–D): live `history-limit`/`mouse` options, operator scroll/return-to-live, copy/detach/consistency, and `docker port` showing no new inbound mapping (contract C8 / FR-009). **Deferred — no Docker daemon in this dev container; run on the Mac/deploy side. The docker-gated tests in `tests/integration/test_scrollback_history.py` automate section B and skip cleanly here.**
- [X] T016 [P] Confirm no regression to the existing `tests/unit/test_session_script.py` and `tests/integration/test_serve_pairing.py` — the unchanged `asdd-session.sh` must still drive tmux as before.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately (T001 then T002).
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS both user stories (creates the shared config + test scaffolding).
- **User Story 1 (Phase 3)**: Depends on Foundational. Independently testable.
- **User Story 2 (Phase 4)**: Depends on Foundational. T009 edits the same config file as T006, so US2's config edit follows US1's (sequential on that file); its tests (T010, T011) are independent.
- **User Story 3 (Phase 5)**: Depends on US1+US2 having set the server-global options (it verifies their cross-entry-point consistency). No new config.
- **Polish (Phase 6)**: Depends on all desired stories complete.

### Within Each User Story

- Config directive → unit assertion (`[P]`, isolated assertion) → docker-gated integration assertion.

### Parallel Opportunities

- T007 and T010 are `[P]` — they add independent assertions and can be authored in parallel once their respective config directives exist.
- T016 is `[P]` with T014/T015.
- The two config edits (T006, T009) are **not** parallel — same file (`asdd-tmux.conf`).
- Integration tests (T008, T011) touch the same new test file; sequence them or author as separate functions to avoid edit conflicts.

---

## Parallel Example: tests after config directives exist

```bash
# Once T006 (history-limit) and T009 (mouse on) are in the config file:
Task: "T007 [US1] assert history-limit 50000 in tests/unit/test_tmux_config.py"
Task: "T010 [US2] assert mouse on in tests/unit/test_tmux_config.py"
# (Same file — if authored truly concurrently, merge the two assert functions.)
```

---

## Implementation Strategy

### MVP First

This feature's MVP is **both P1 stories together** (US1 long history + US2 mouse scroll), because they are the two directives of one config file and the user asked for both ("scroll with mouse, and have a long history"). Sequence:

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → 4. Phase 4 US2.
5. **STOP and VALIDATE**: rebuild image, run quickstart B–C → operator has long, mouse-scrollable history. Ship.

### Incremental Delivery

1. Setup + Foundational → config wired and loadable.
2. US1 → history depth verified.
3. US2 → mouse scrolling verified → **MVP shippable**.
4. US3 → cross-entry-point parity confirmed + operator docs.
5. Polish → full quickstart + regression sweep.

---

## Notes

- This is a container-config change: no `src/` code, no new Python or system dependency (tmux already installed). The three-Python-deps invariant is unaffected.
- `asdd-session.sh` is intentionally **not** modified — tmux auto-loads `/etc/tmux.conf` at server start.
- Watch-point from research R3: if a future Claude Code version captures the mouse wheel (mouse-tracking mode), `mouse on` would forward wheel events to the app; the large `history-limit` still fixes the Shift+wheel path. Note it during T015 validation, not a blocker now.
- Commit after each logical group; keep the config edits and their tests together.
