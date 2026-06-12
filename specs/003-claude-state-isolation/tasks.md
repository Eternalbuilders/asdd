---
description: "Task list for 003-claude-state-isolation"
---

# Tasks: Per-project Claude state isolation under the shared auth store

**Input**: Design documents from `/specs/003-claude-state-isolation/`

**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓

**Tests**: Tests REQUESTED — the spec's user-story Independent Test sections specify concrete checks, and the contracts call out a unit-test contract. Test tasks are included.

**Organization**: Tasks are grouped by user story. US1 (no leakage) and US2 (shared credential) are inseparable at the implementation level — the single `auth_mounts()` API change delivers both — so they share Phase 3 with `[US1]` `[US2]` joint labels on the shared tasks.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps to spec.md user stories (US1, US2, US3, US4)
- File paths are absolute or repo-root relative

## Path conventions

Existing single-Python-project layout from plan.md: `asdd/` for source, `tests/{unit,integration}/` for tests. No new top-level directories.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: This feature is additive to an existing project. No new dependencies, no new directory layout, no scaffolding. Phase 1 is intentionally empty.

_No tasks._

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Pure helper functions in `asdd/auth.py` that every user story consumes. These have no dependencies on each other beyond the existing `auth.py` surface, and nothing else can land until they exist.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T001 [P] Add module constant `PER_PROJECT_DIRNAME = "per-project"` and helper `per_project_root(asdd_home: Path) -> Path` returning `store_dir(asdd_home) / PER_PROJECT_DIRNAME` to `asdd/auth.py` (near the other path helpers at lines 54-71).
- [X] T002 [P] Add helper `per_project_dir(asdd_home: Path, project_id: str) -> Path` returning `per_project_root(asdd_home) / project_id` to `asdd/auth.py`. Add both helpers to the `__all__` export list at the bottom of the file.
- [X] T003 [P] Add module constants `LEGACY_NOTICE_FILENAME = ".migration-notice-shown"` and helper `legacy_notice_marker(asdd_home: Path) -> Path` returning `store_dir(asdd_home) / LEGACY_NOTICE_FILENAME` to `asdd/auth.py`. Also export from `__all__`.
- [X] T004 [P] Add helper `legacy_state_present(asdd_home: Path) -> bool` to `asdd/auth.py` returning `(store_claude_dir(asdd_home) / "projects").is_dir()`. Export from `__all__`.
- [X] T005 Modify `asdd/auth.py:ensure_mountable(asdd_home)` to accept an optional `project_id: str | None = None` keyword argument. When `project_id` is supplied, additionally materialise `per_project_dir(asdd_home, project_id)` as a `0700` directory (use `mkdir(parents=True, exist_ok=True)` then `os.chmod`). Also materialise `credentials_file(asdd_home)` as an empty placeholder file (`0600`) when missing — reuse the same `_heal_json_is_dir`-style guard pattern used for `claude.json` at lines 181-185. Update the docstring to describe both new behaviours.
- [X] T006 Modify `asdd/auth.py:clear(asdd_home)` to remove the entire `store_dir(asdd_home)` tree (which now contains `per-project/` alongside `claude/` and `claude.json`). The current `_rmtree(d)` call already does this; verify by reading the current code and adjusting only if the implementation has narrowed the scope. Update the docstring to call out per-project cleanup.
- [X] T007 [P] Extend `tests/unit/test_auth.py` with cases for the new helpers: `test_per_project_dir_path_shape`, `test_legacy_state_present_negative_on_empty_store`, `test_legacy_state_present_positive_when_claude_projects_exists`, `test_legacy_notice_marker_path`. Place near the existing path-helper tests around line 46.
- [X] T008 [P] Extend `tests/unit/test_auth.py` with cases for the extended `ensure_mountable`: `test_ensure_mountable_materialises_per_project_dir`, `test_ensure_mountable_creates_credentials_placeholder_when_missing`, `test_ensure_mountable_does_not_clobber_existing_credentials`, `test_ensure_mountable_no_project_id_skips_per_project`. Verify `0700` on the per-project dir and `0600` on the placeholder file.
- [X] T009 [P] Extend `tests/unit/test_auth.py` with cases for the extended `clear`: `test_clear_removes_per_project_subtrees`, `test_clear_removes_legacy_notice_marker`. Stand up a store with `per-project/p/` and `.migration-notice-shown` first, then `clear`, then assert both are gone.

**Checkpoint**: `asdd/auth.py` exposes the per-project + migration-detection surface; unit tests cover it. User stories can now build on top.

---

## Phase 3: User Story 1 + User Story 2 — Isolation + shared credentials (Priority: P1) 🎯 MVP

**Goal**: A single change to the container mount table delivers both user stories together: each project's container sees only its own `~/.claude/` per-project state (US1), while OAuth credentials and account config remain shared from one host-side store (US2). Token refresh in one project is visible to all on next start (US2's acceptance scenario 2) because every container points at the same `.credentials.json` host file.

**Independent Test (US1)**: Two containers for two distinct projects. Write a sentinel file under `~/.claude/projects/-asdd-home/` from project A's container; confirm absent in project B's container.

**Independent Test (US2)**: From two project containers, `stat ~/.claude/.credentials.json` returns the same host inode (or same content + size + mtime); a single `asdd login` covers both.

### Tests for User Story 1 + 2

- [X] T010 [P] [US1] [US2] Extend `tests/unit/test_project_container.py:test_auth_mounts_maps_store_to_user_home` (currently at line 41) and add new cases asserting the contract from `contracts/auth-mounts.md`:
  - `test_auth_mounts_with_project_id_returns_three_tuples_in_order` — container paths `[~/.claude.json, ~/.claude, ~/.claude/.credentials.json]` in that exact order; all modes `"rw"`.
  - `test_auth_mounts_without_project_id_returns_two_shared_tuples` — paths `[~/.claude.json, ~/.claude/.credentials.json]`; no `~/.claude` directory mount.
  - `test_auth_mounts_threads_project_id_to_ensure_mountable` — after the call, `per_project_dir(home, "p")` exists with mode `0700`.
- [X] T011 [P] [US1] [US2] Extend `tests/unit/test_project_container.py` cases for `autonomous_mounts` and `interactive_mounts`: assert each forwards `project_id` to `auth_mounts` and that the resulting argv contains the per-project mount target.
- [X] T012 [P] [US1] [US2] Add `tests/unit/test_project_container.py:test_start_container_per_project_state_dir_mounted` — assert the rendered `docker run` argv (captured via the existing `_fake_run_capture` fixture used at line 65 onward) contains `-v <…>/per-project/<project_id>:/home/asdd/.claude:rw` AND a separate `-v <…>/claude/.credentials.json:/home/asdd/.claude/.credentials.json:rw` mount appearing AFTER the directory mount.
- [X] T013 [P] [US1] [US2] Create `tests/integration/test_state_isolation.py` (docker-gated like other integration tests under `tests/integration/`). Two test cases skipped if docker absent:
  - `test_two_projects_dont_see_each_others_per_project_state` — start container A, write `~/.claude/projects/-asdd-home/sentinel-a.txt`; stop. Start container B, confirm absence; write `~/.claude/projects/-asdd-home/sentinel-b.txt`; stop. Start container A again, confirm sentinel-b absent; confirm sentinel-a present.
  - `test_shared_credentials_visible_in_both_projects` — write a sentinel into the host shared `.credentials.json` (a JSON blob), start both containers, confirm both see identical content.

### Implementation for User Story 1 + 2

- [X] T014 [US1] [US2] Modify `asdd/project_container.py:auth_mounts` signature at line 95 to `auth_mounts(asdd_home: Path, project_id: str | None = None)`. Call `auth.ensure_mountable(asdd_home, project_id=project_id)` instead of the no-arg form. Return tuples per `contracts/auth-mounts.md`:
  - 2 tuples when `project_id is None`: `(store_json_path, ~/.claude.json, rw)` then `(credentials_file, ~/.claude/.credentials.json, rw)`.
  - 3 tuples when `project_id is supplied`: prepend the directory mount `(per_project_dir(asdd_home, project_id), ~/.claude, rw)` between the two shared mounts so the order is `[claude.json, ~/.claude dir, .credentials.json file]`.

  Update the docstring to describe the new layered-mount semantics and reference research decision R2 on mount ordering.
- [X] T015 [US1] [US2] Update `asdd/project_container.py:_compose_mounts` (around line 123) to call `auth_mounts(pc.asdd_home, pc.project_id)` instead of `auth_mounts(pc.asdd_home)`. The `ProjectContainer` dataclass already carries `project_id` — verify by reading the dataclass definition near line 70.
- [X] T016 [US1] [US2] Update `asdd/project_container.py:interactive_mounts` (around line 136) signature to `interactive_mounts(workspace_path, asdd_home=None, *, project_id=None)`. Pass `project_id` through to `auth_mounts`. Update all callers in the same module.
- [X] T017 [US1] [US2] Update `asdd/project_container.py:autonomous_mounts` (around line 144) signature to `autonomous_mounts(workspace_path, asdd_home=None, *, project_id=None, use_api_key=False)`. Pass `project_id` through to `auth_mounts`. Update all callers.
- [X] T018 [US2] Verify `asdd/project_container.py:interactive_login_run` (around line 517) — the throwaway-login flow — calls `auth_mounts(asdd_home)` (no project_id, gets only the 2 shared mounts). Already correct if T014 defaults `project_id=None`; just add a comment at line 535 referencing FR-010 and `contracts/auth-mounts.md` Case A to make the intent explicit.

**Checkpoint**: P1 MVP delivered. Unit tests green; integration test (if docker available) green. Stop here and validate against the spec's US1+US2 acceptance scenarios before moving on.

---

## Phase 4: User Story 3 — Project archive removes per-project Claude state (Priority: P2)

**Goal**: When `asdd archive <project_id>` runs (the existing project-lifecycle removal path in `asdd/bootstrap.py:cmd_archive`), the project's per-project Claude state directory is also removed.

**Independent Test**: Create a project, materialise a sentinel file under `_state/claude-auth/per-project/<id>/projects/`, archive the project, confirm the per-project state directory is gone while a second project's directory is untouched.

### Tests for User Story 3

- [X] T019 [P] [US3] Add `tests/unit/test_bootstrap.py:test_cmd_archive_removes_per_project_claude_state` (or extend existing archive tests if present — search for `cmd_archive` test cases first). Stand up two projects with per-project subtrees, archive one, assert that one's tree is removed and the other's is intact.
- [X] T020 [P] [US3] Add `tests/unit/test_bootstrap.py:test_cmd_archive_idempotent_when_per_project_state_absent` — archive a project that never started a container (no per-project subtree). No error.

### Implementation for User Story 3

- [X] T021 [US3] Modify `asdd/bootstrap.py:cmd_archive` (around line 310) to remove the per-project Claude state directory after the container is removed and before the tarball snapshot step. Use `shutil.rmtree(auth.per_project_dir(asdd_home, project_id), ignore_errors=True)`. Add a `_emit_progress("per_project_state_removed", project_id=...)` line so the operation is observable. Import `from asdd import auth` if not already imported.

**Checkpoint**: Archiving a project cleans up its per-project Claude state. Re-run quickstart section 3.

---

## Phase 5: User Story 4 — Upgrade migration notice (Priority: P2)

**Goal**: An upgrading operator with pre-existing mixed state in `_state/claude-auth/claude/projects/` sees a one-time notice on first container start. No silent migration, no silent deletion.

**Independent Test**: Stand up a fake legacy state (mixed transcripts under the shared store), remove the migration-notice marker, run `start_container`, assert the notice appears once on stderr and the marker file is created. Run again, assert no second notice.

### Tests for User Story 4

- [X] T022 [P] [US4] Add `tests/unit/test_project_container.py:test_start_container_emits_migration_notice_on_first_run_with_legacy_state`. Use the existing `_fake_run_capture` fixture pattern (line 65 onward). Pre-seed `_state/claude-auth/claude/projects/-asdd-home/` and ensure the marker is absent. Assert the notice text appears on stderr and that `auth.legacy_notice_marker(home)` exists afterward.
- [X] T023 [P] [US4] Add `test_start_container_does_not_re_emit_migration_notice` — repeat the setup but pre-create the marker file. Assert no notice on stderr.
- [X] T024 [P] [US4] Add `test_start_container_no_notice_on_clean_install` — fresh home with no legacy state, no marker, no notice.

### Implementation for User Story 4

- [X] T025 [US4] Add helper `_maybe_emit_legacy_state_notice(asdd_home: Path) -> None` to `asdd/project_container.py` (near the other private helpers). Logic: if `auth.legacy_state_present(asdd_home)` and not `auth.legacy_notice_marker(asdd_home).exists()`, write the notice text to `sys.stderr` (use `click.echo(..., err=True)` since click is already imported), then `touch` the marker file with mode `0600`.

  Notice text — single line on stderr:

      asdd: legacy mixed Claude state detected at _state/claude-auth/claude/projects/. Per-project isolation now applies to new sessions. Run `asdd logout && asdd login` for a clean slate if desired.

- [X] T026 [US4] Call `_maybe_emit_legacy_state_notice(pc.asdd_home)` at the top of `asdd/project_container.py:start_container` (around line 215, right after the docstring), guarded so it only fires when `pc.asdd_home is not None`. Idempotent across multiple invocations because the marker prevents re-emission.

**Checkpoint**: Upgrading operators see exactly one notice on first start; fresh installs see nothing.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T027 [P] Update `CLAUDE.md` invariants table (lines 73-79 of the current file) to reflect the new mount layout: change the "Subscription auth is the default for all modes" row's description to mention that per-project Claude state lives in `_state/claude-auth/per-project/<id>/` and only credentials are shared. Add a new row: "Per-project Claude state never crosses project boundaries — `_state/claude-auth/per-project/<id>/` is one project's state and is removed on archive."
- [X] T028 [P] Update `README.md` if it mentions the auth store layout — search with `grep -n "claude-auth" README.md USER_GUIDE.md`. Update any path documentation to reflect the per-project subtree.
- [X] T029 [P] Run `make lint` and fix any lint findings introduced by the change.
- [X] T030 Run `make test`; confirm all 106 pre-existing unit tests still pass and the new ones (T007-T012, T019-T020, T022-T024) pass too.
- [X] T031 Walk through `specs/003-claude-state-isolation/quickstart.md` end-to-end if docker is available locally. Document any deviation. Sections 1, 2, 3, 4, 5 are independently runnable; section 6 (persistent session) requires spec 010's `asdd serve` and can be skipped if unavailable.

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (Setup)**: empty.
- **Phase 2 (Foundational)**: must complete before any user story phase. T001–T004 are `[P]` (different functions, same file but additive — they can run as separate edits in any order). T005 depends on T002 (uses `per_project_dir`). T006 has no incoming dependency. T007–T009 are `[P]` and depend on T001–T006 being merged.
- **Phase 3 (US1+US2)**: depends on Phase 2 complete. Tests T010-T013 can be written `[P]`. Implementation T014 is the linchpin; T015-T018 each `[P]` depend on T014 but are different files / different functions.
- **Phase 4 (US3)**: depends on Phase 2 complete; independent of Phase 3.
- **Phase 5 (US4)**: depends on Phase 2 complete; independent of Phases 3 and 4 in principle, but T026 edits `start_container` which Phase 3 also touches indirectly — sequence Phase 5 after Phase 3 to avoid merge conflicts.
- **Phase 6 (Polish)**: depends on all desired user stories being landed.

### Story-level dependencies

- **US1 + US2**: combined Phase 3, no other story dependencies.
- **US3**: independent of US1+US2 at the code level (different files); same Phase 2 prerequisites.
- **US4**: independent of US3; depends on Phase 2; orders after Phase 3 only for diff hygiene.

### Within each story

- Tests written first (no TDD discipline forced — but the contract tests in T010-T012 are concrete enough that writing them first makes the implementation tasks self-checking).
- For Phase 3: T014 (the auth_mounts API change) MUST land before T015-T018; the callers can't compile without the new signature.

### Parallel opportunities

- Phase 2: T001, T002 (after T002), T003, T004 can be edits to `asdd/auth.py` in one PR or four — all additive.
- Phase 2 tests: T007, T008, T009 are independent test functions in the same file; can be authored in parallel by different developers.
- Phase 3 tests: T010-T013 are independent (3 unit-test cases + 1 new integration-test file).
- Phase 3 callers: T015, T016, T017, T018 each touch different existing call sites — can land in separate commits after T014.
- Phase 4: T019, T020 are parallel test cases.
- Phase 5: T022, T023, T024 are parallel test cases.
- Phase 6: T027, T028, T029 each touch different files.

---

## Parallel Example: User Story 1 + 2

```bash
# Land Phase 2 first (one or more commits to asdd/auth.py + tests/unit/test_auth.py)

# Then in parallel:
Task: "T010 — add three auth_mounts contract tests to tests/unit/test_project_container.py"
Task: "T011 — add interactive/autonomous mounts forwarding tests"
Task: "T012 — add start_container argv mount-ordering test"
Task: "T013 — create tests/integration/test_state_isolation.py"

# Implementation lockstep:
Task: "T014 — change auth_mounts signature in asdd/project_container.py"   # blocks T015-T018

# After T014, in parallel:
Task: "T015 — update _compose_mounts"
Task: "T016 — update interactive_mounts"
Task: "T017 — update autonomous_mounts"
Task: "T018 — comment in interactive_login_run"
```

---

## Implementation Strategy

### MVP first (US1 + US2 — the P1 combined phase)

1. Phase 2 (Foundational): land `asdd/auth.py` helpers and tests.
2. Phase 3: land the `auth_mounts` signature change + callers + tests.
3. **STOP AND VALIDATE**: run `make test`; spot-check the integration test against a real two-container setup if docker is available. Confirm against the spec's US1 + US2 acceptance scenarios.
4. Ship MVP. The bug the user reported is fixed at this point. US3 and US4 are quality-of-life follow-ups.

### Incremental delivery

1. MVP (above) → demo/validate.
2. Phase 4 (US3 archive cleanup) → demo.
3. Phase 5 (US4 migration notice) → demo.
4. Phase 6 polish → final.

Each phase is independently shippable.

---

## Notes

- `[P]` tasks are different files OR additive non-overlapping edits to the same file (e.g., adding distinct helper functions to `auth.py`).
- This feature has no infrastructure / framework setup. Phase 1 is intentionally empty.
- Migration notice (Phase 5) is a one-time operator-visible side effect on first post-upgrade `start_container`; no historical state is modified.
- The integration test in T013 will skip cleanly when docker is unavailable, matching the existing `tests/integration/` convention.
- After implementation, `quickstart.md` is the operator-facing validation runbook — run it before marking the feature done.
