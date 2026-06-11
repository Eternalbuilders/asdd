---
description: "Task list for feature 001-container-shell-and-gh"
---

# Tasks: Container shell vs. Claude entry points, container-aware prompt, preinstalled `gh`

**Input**: Design documents in `/asdd_home/specs/001-container-shell-and-gh/`
**Prerequisites**: spec.md, plan.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included. The plan calls out unit tests for each CLI surface and integration tests for the image contract; we follow that.

**Organization**: tasks are grouped by user story so each can ship as an independent increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- File paths are absolute from `/asdd_home/`.

## Path Conventions

- CLI source: `asdd/`
- Container image source: `docker/`
- Tests: `tests/unit/` and `tests/integration/`
- Docs: `README.md`, `USER_GUIDE.md`, `CLAUDE.md`, `project_skeleton/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: nothing to set up — the repo, Click app, pytest harness, and Docker pipeline already exist. This phase is intentionally empty; no setup tasks are required for this feature.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: ship the runtime substrate that both `asdd open` (revised) and `asdd claude` (new) depend on. Until this phase lands, no user story can be implemented because all four require `ASDD_PROJECT_ID` plumbing and a refreshed image.

- [X] T001 Add `ASDD_PROJECT_ID` to the env vars that `start_container` plumbs into the container in `asdd/project_container.py` (insert into the `extra_env` it composes; do not change the public signature).
- [X] T002 [P] Create `docker/files/asdd-prompt.sh` with the bash snippet from `specs/001-container-shell-and-gh/contracts/container-image.md` (interactive-only, idempotent, composes around the user's PS1).
- [X] T003 [P] In `docker/Dockerfile.project`, bump `ARG GH_VERSION=2.92.0` to `ARG GH_VERSION=2.94.0` and add an inline comment naming the policy ("bump intentionally per asdd minor release; do not float to `latest`").
- [X] T004 In `docker/Dockerfile.project`, add `COPY --chmod=0644 docker/files/asdd-prompt.sh /etc/profile.d/asdd-prompt.sh` directly after the existing `asdd-session.sh` COPY line.
- [X] T005 Add unit test in `tests/unit/test_project_container.py` asserting that `start_container` passes `ASDD_PROJECT_ID=<project_id>` on the `docker create`/`docker run` command line (use the existing `monkeypatch.setattr(subprocess, "run", spy)` pattern in that file).

**Checkpoint**: Foundation ready — user story implementation can begin.

---

## Phase 3: User Story 1 — `asdd open` is a shell, never Claude (Priority: P1) 🎯 MVP

**Goal**: `asdd open <project>` drops the operator at a bash prompt with no Claude involvement, and refuses cleanly when a persistent session is running.

**Independent Test**: per quickstart §US1 — `asdd open my-app` lands at a bash prompt, `pgrep -fl claude` shows nothing, `exit` returns to host with no orphaned container.

### Implementation for User Story 1

- [X] T006 [US1] In `asdd/bootstrap.py`'s `cmd_open`, replace the persistent-session branch (`if is_persistent_running(...): return project_container.attach_session(...)`) with raising `project_container.AlreadyRunningError(project_id, mode="persistent")` (or a `ProjectContainerError` with a message naming `asdd attach` / `asdd claude` as the right command). Update the function docstring.
- [X] T007 [US1] In `asdd/bootstrap.py`, update the `@cli.command("open", help=…)` help string to: `"Open a project's container at an interactive bash shell (no Claude)."`.
- [X] T008 [US1] In `tests/unit/test_persistent_session.py`, replace `test_open_attaches_when_persistent` with `test_open_refuses_when_persistent`: assert `cmd_open` raises (or `_cli_open` exits 1 with the expected message) and `attach_session` is NOT called.

**Checkpoint**: User Story 1 fully functional. Verify with quickstart §US1 and §US2.c.

---

## Phase 4: User Story 2 — `asdd claude` starts a Claude session (Priority: P1)

**Goal**: `asdd claude <project>` is a new top-level command that runs Claude inside the project's interactive container, re-attaching to a persistent session if one is running.

**Independent Test**: per quickstart §US2 and §US2.b — `asdd claude my-app` opens Claude; if a persistent session is up, it re-attaches via tmux.

### Implementation for User Story 2

- [X] T009 [US2] In `asdd/project_container.py`, add `attach_claude(project_id: str) -> int` parallel to `attach_shell` — runs `subprocess.run(["docker", "exec", "-it", container_name(project_id), "claude"], check=False)` and returns the returncode. Add `"attach_claude"` to the module's `__all__`.
- [X] T010 [P] [US2] In `asdd/bootstrap.py`, add `cmd_claude(*, asdd_home: Path, project_id: str) -> int` following the same control flow as `cmd_open` but calling `attach_claude` instead of `attach_shell` and PRESERVING the persistent-session re-attach (`if is_persistent_running: return attach_session(...)`).
- [X] T011 [US2] In `asdd/bootstrap.py`, add a Click command `@cli.command("claude", help="Start an interactive Claude Code session in a project's container.")` that wraps `cmd_claude` with the same error→`sys.exit(1)` translation as `_cli_open`.
- [X] T012 [P] [US2] In `tests/unit/test_project_container.py`, add a test that `attach_claude` invokes `docker exec -it <name> claude` (use the same subprocess-spy pattern as the existing `attach_shell` test).
- [X] T013 [US2] In `tests/unit/test_persistent_session.py`, add `test_claude_attaches_when_persistent`: when `is_persistent_running` returns true, `cmd_claude` calls `attach_session` and returns its return code (mirror the old `test_open_attaches_when_persistent` shape).
- [X] T014 [US2] In `tests/unit/test_bootstrap_cli.py` (create the file if it doesn't exist; otherwise extend), use `click.testing.CliRunner` to verify `asdd claude` exits 0 on the happy path (monkeypatched `cmd_claude`) and exits 1 with stderr on `BootstrapError` and `AlreadyRunningError`.

**Checkpoint**: User Story 2 fully functional. Verify with quickstart §US2 and §US2.b.

---

## Phase 5: User Story 3 — Shell prompt shows project name (Priority: P2)

**Goal**: every interactive shell inside an asdd container shows `(<project>) ` in PS1.

**Independent Test**: per quickstart §US3 and §US3.b — open two project containers in two terminals; each prompt names the correct project; a sub-shell preserves the prefix; host shell is unaffected.

### Implementation for User Story 3

- [X] T015 [US3] Verify `docker/files/asdd-prompt.sh` is exactly the snippet in `specs/001-container-shell-and-gh/contracts/container-image.md`. (Most of the work happened in Phase 2 — T002 plus T004 wire the file into the image. This task is a sanity-check pass + manual verification per quickstart.)
- [X] T016 [US3] In `tests/integration/test_image_smoke.py` (create if absent), add a test that builds (or assumes-built) the image and asserts `docker run --rm -e ASDD_PROJECT_ID=foo asdd/project:latest bash -lic 'echo "$PS1"'` produces output containing `(foo)`. Mark the test `pytest.skip` if Docker is not available, matching the existing convention.
- [X] T017 [US3] In the same file, add a counterpart test: without `ASDD_PROJECT_ID`, the output does NOT contain a leading `(` — ensures no leakage when the env var is unset.

**Checkpoint**: User Story 3 fully functional. Verify with quickstart §US3 and §US3.b.

---

## Phase 6: User Story 4 — `gh` preinstalled in every new container (Priority: P2)

**Goal**: a freshly built image has a working, pinned `gh` on `$PATH` for both amd64 and arm64.

**Independent Test**: per quickstart §US4 — `gh --version` exits 0 with a 2.94.x string; `gh auth login` walks through the device-code flow.

### Implementation for User Story 4

- [X] T018 [US4] Confirm Phase 2 T003 bumped `GH_VERSION` to `2.94.0` and that the existing arch-aware `RUN` block in `docker/Dockerfile.project` still resolves correctly (no extra changes if T003 landed cleanly).
- [X] T019 [US4] In `tests/integration/test_image_smoke.py`, add a test that `docker run --rm asdd/project:latest gh --version` exits 0 and stdout matches `^gh version 2\.94\.`. Skip when Docker is unavailable.

**Checkpoint**: User Story 4 fully functional. Verify with quickstart §US4.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: doc surfaces and a final regression sweep.

- [X] T020 [P] In `README.md`, change every sentence that says or implies "`asdd open` drops you into Claude" to reflect the new split — `asdd open` → shell, `asdd claude` → Claude.
- [X] T021 [P] In `USER_GUIDE.md`, do the same edit. If there's a worked example walkthrough, update it to use `asdd claude` for the Claude-session step.
- [X] T022 [P] In `CLAUDE.md`, update the "operating modes" section so the two interactive entry points are named explicitly. Keep the SPECKIT plan-reference block intact.
- [X] T023 [P] If `project_skeleton/` contains a `CLAUDE.md` or README that describes the entry-point flow, update it consistently with T020–T022. (If no such file exists, this task is a no-op — confirm and tick off.)
- [X] T024 Run `make test` from the repo root; assert all unit tests pass and Docker-dependent integration tests skip cleanly when Docker is absent.
- [X] T025 Run `make lint`; fix any new findings before pushing.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: empty — nothing blocks anything.
- **Phase 2 (Foundational)**: T001–T005. Blocks all user stories.
  - T001 must precede T005 (the test verifies the behavior T001 introduces).
  - T002, T003, T004 are an image-build trio: T002 and T003 are independent; T004 references T002's file.
- **Phase 3 (US1)**: T006 → T007 → T008. T008 verifies T006.
- **Phase 4 (US2)**: T009 → T010 → T011 → (T012, T013, T014 in parallel). T011 depends on T010 (Click wiring needs the handler); T014 depends on T011.
- **Phase 5 (US3)**: T015 → (T016, T017 in parallel). All require Phase 2 to have shipped.
- **Phase 6 (US4)**: T018 → T019. Both require Phase 2 to have shipped.
- **Phase 7 (Polish)**: T020, T021, T022, T023 in parallel; T024, T025 sequentially at the very end.

### User Story Dependencies

- US1 depends only on Phase 2.
- US2 depends only on Phase 2.
- US3 depends only on Phase 2 (the env-var plumbing).
- US4 depends only on Phase 2 (the Dockerfile bump).
- All four stories are independent of each other after Phase 2; they can be implemented in parallel.

### Parallel Opportunities

- **Within Phase 2**: T002 ∥ T003.
- **Within Phase 4 (US2)**: after T011, run T012, T013, T014 in parallel.
- **Within Phase 5 (US3)**: after T015, run T016 ∥ T017.
- **Across stories** (after Phase 2): US1, US2, US3, US4 in parallel if multiple committers are available.
- **Within Phase 7**: T020 ∥ T021 ∥ T022 ∥ T023.

---

## Parallel Example: User Story 2

```bash
# After T011 wires the Click command:
Task: "Unit test attach_claude subprocess call in tests/unit/test_project_container.py"        # T012
Task: "Unit test persistent re-attach for asdd claude in tests/unit/test_persistent_session.py" # T013
Task: "CLI runner happy/auth/already-running paths in tests/unit/test_bootstrap_cli.py"         # T014
```

---

## Implementation Strategy

### MVP First (User Story 1 + Story 2 together)

User Story 1 alone is not a useful MVP — it merely codifies existing behavior. The smallest shippable value is `US1 + US2`: the split is what the operator actually asked for. After Phase 2 lands, do US1 and US2 in one push, validate via quickstart, then layer US3 (prompt) and US4 (gh) as follow-ups.

1. Phase 2 (T001–T005).
2. Phase 3 (T006–T008) — `asdd open` codified as shell-only.
3. Phase 4 (T009–T014) — `asdd claude` shipped.
4. Validate against quickstart §US1 and §US2 / §US2.b / §US2.c.
5. Deploy / merge (this is the MVP — already useful).

### Incremental Delivery

6. Phase 5 (T015–T017) — prompt prefix. Quickstart §US3 / §US3.b.
7. Phase 6 (T018–T019) — `gh` smoke. Quickstart §US4.
8. Phase 7 (T020–T025) — docs + final test/lint sweep.

### Parallel Team Strategy

Single-implementer for this feature (small scope). If split:

- Implementer A: Phase 2 + Phase 3 + Phase 4.
- Implementer B: (after Phase 2 lands) Phase 5 + Phase 6.
- Either: Phase 7.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks.
- [Story] label maps tasks to spec.md user stories.
- File paths are absolute under `/asdd_home/`.
- Commit after each phase (or each story within Phase 2's body) for a clean PR history.
- The constitution forbids new third-party Python deps; this feature adds zero, so the existing `pyproject.toml` dep set stays at exactly three (`PyYAML`, `jsonschema`, `click`).
