# Tasks: Container Auto Permission Mode for Git

**Feature**: `006-container-auto-permission-mode` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

Tests are included (the repo invariant requires `make test` green before commit;
unit tests mirror existing `tests/unit/` style).

## Phase 1: Setup

- [X] T001 Establish a green baseline by running `make test` from repo root before any changes; note current pass count.

## Phase 2: Foundational (blocking prerequisite for US2 and US3)

- [X] T002 Create `project_skeleton/.claude/settings.json` containing the `permissions.deny` rule set exactly as specified in `specs/006-container-auto-permission-mode/contracts/permission-settings.md` (no `permissions.defaultMode`).

**Checkpoint**: the canonical deny-guard contract now exists in the skeleton; US2 and US3 can build on it.

## Phase 3: User Story 1 — Git just works in every container (Priority: P1)

**Goal**: every container launch path starts Claude in `auto` mode so routine git/`gh` run without per-command approval.

**Independent test**: start a container in each mode, run `git status`/commit — no approval prompt appears.

- [X] T003 [US1] In `docker/files/asdd-session.sh`, add `--permission-mode auto` to BOTH claude invocations — the `--continue` resume call (≈L45) and the fresh-start call (≈L48).
- [X] T004 [P] [US1] In `docker/files/asdd-run-job.sh`, add `--permission-mode auto` to the `claude --print` invocation (≈L41).
- [X] T005 [P] [US1] In `asdd/project_container.py`, add `--permission-mode auto` to the `claude` command built by `attach_claude` (≈L448); leave `_login_in_container` (≈L688) unchanged.
- [X] T006 [US1] Add/extend unit test in `tests/unit/test_session_script.py` asserting `asdd-session.sh` (both claude lines) and `asdd-run-job.sh` carry `--permission-mode auto`, that `attach_claude` includes it, and that the login path does not (per `contracts/container-launch.md`).

**Checkpoint**: US1 independently testable — git runs unprompted in serve, dispatch, and interactive modes.

## Phase 4: User Story 2 — Destructive git stays blocked (Priority: P1)

**Goal**: force-push, hard reset, rebase, and `--no-verify` commits are refused in every mode, even under auto mode, with no human present.

**Independent test**: in any mode, attempt each destructive command — each is blocked while routine git is auto-approved.

- [X] T007 [P] [US2] Add a unit test (e.g. `tests/unit/test_skeleton_permissions.py`) asserting `project_skeleton/.claude/settings.json` parses as JSON and its `permissions.deny` contains the full rule set from the contract.
- [X] T008 [US2] In `asdd/auth.py`, verify `ensure_workspace_trusted` also pre-accepts the "project defines permission rules — approve?" prompt; if it only covers workspace trust, extend it (set the corresponding acceptance in the mounted `claude.json`) so unattended `serve`/`dispatch` do not stall (FR-009). Add/extend a unit test in `tests/unit/test_auth.py`.

**Checkpoint**: deny-guards load unattended and block destructive git in every mode.

## Phase 5: User Story 3 — New and existing projects are covered (Priority: P2)

**Goal**: new projects get the guardrail automatically; existing projects have a defined backfill path.

**Independent test**: scaffold a new project → file present with zero manual steps; run the backfill on an old project → file present there too.

- [X] T009 [US3] In `asdd/workspace.py:scaffold`, after the constitution copy, write `templates_root / ".claude" / "settings.json"` to `<workspace>/.claude/settings.json` (create the dir if absent; write only the file — do NOT overwrite the `.claude/` dir created by `specify init`); idempotent like the existing steps.
- [X] T010 [P] [US3] Add/extend a unit test in `tests/unit/test_workspace*.py` asserting `scaffold` produces `<workspace>/.claude/settings.json` with the deny rules and does not clobber other `.claude/` contents.
- [X] T011 [US3] Document the backfill step in `USER_GUIDE.md` (copy `${ASDD_HOME}/_templates/.claude/settings.json` into existing `${ASDD_HOME}/projects/<id>/.claude/settings.json`), per `quickstart.md` step 5.

**Checkpoint**: US3 independently testable — coverage for both new and existing projects.

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T012 Update `USER_GUIDE.md`: document that all container modes now start in `auto` permission mode with deny-guards, and remove/revise the prior instruction that operators must start sessions in automode themselves via `claude --dangerously-skip-permissions` (FR-010).
- [X] T013 Run `make lint && make test` from repo root; ensure green (all prior tests plus the new ones).
- [ ] T014 [P] Optional manual end-to-end pass on the Mac following `quickstart.md` steps 2–6 (auto-approve git, block destructive, backfill, confirm "Allowed by auto mode classifier"). DEFERRED — requires Docker + a logged-in Mac; not runnable from the dev container. Owner: operator.

## Dependencies & completion order

- **Setup (T001)** → no dependencies.
- **Foundational (T002)** → blocks US2 (T007) and US3 (T009/T010). Must come first.
- **US1 (T003–T006)** → depends only on Setup; independent of US2/US3. Can be delivered as the first increment.
- **US2 (T007–T008)** → T007 depends on T002; T008 is independent code in `auth.py`.
- **US3 (T009–T011)** → T009/T010 depend on T002; T011 is docs.
- **Polish (T012–T014)** → after the stories; T013 gates the commit.

## Parallel execution examples

- After T002: `T004`, `T005` (different files) can run in parallel with each other and with `T007`, `T010` authoring.
- `T007` (skeleton-content test) and `T010` (scaffold test) are independent files — parallelizable.
- T003 is NOT parallel with itself (single file, two edits); keep it one task.

## Implementation strategy

- **MVP = US1** (T001–T006): auto mode everywhere makes git frictionless — the
  core ask. Shippable on its own (deny-guards from T002 already present as the
  safety floor).
- **Increment 2 = US2** (T007–T008): lock in unattended deny-guard loading.
- **Increment 3 = US3** (T009–T011): automatic provisioning + backfill.
- **Polish** (T012–T014): docs + green gate.

Recommended order honours the dependency graph: T001 → T002 → US1 → US2 → US3 → Polish.
