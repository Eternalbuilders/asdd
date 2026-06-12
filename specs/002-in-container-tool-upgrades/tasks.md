---
description: "Tasks for feature 002 — Convenient & Secure In-Container Tool Upgrades"
---

# Tasks: Convenient & Secure In-Container Tool Upgrades

**Input**: Design documents in `specs/002-in-container-tool-upgrades/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Unit tests (`tests/unit/`) are required for every new module (registry, manifest, version-check, banner, command handlers). One integration test (`tests/integration/`) gated on Docker covers the end-to-end upgrade flow against a real container.

**Organization**: Tasks are grouped by user story so each can be implemented and tested independently. The plan's "Notes for `/speckit-tasks`" sequencing is preserved within phases.

## Format

- `[ ] T### [P?] [Story?] Description with file path`
- `[P]`: Different file, parallelizable
- `[USn]`: Required for Phase 3+ tasks
- Paths are relative to repo root.

---

## Phase 1: Setup

**Purpose**: One-time scaffolding shared by every later phase.

- [X] T001 Add `asdd/tools.py` skeleton with `ManagedTool` dataclass, `TOOLS` registry initialized for `claude`/`gh`/`uv`, and the `ToolDriver` Protocol.
- [X] T002 Add `asdd/tool_manifest.py` skeleton with `Manifest` dataclass, the `acquire_lock`/`release_lock` helpers (fcntl.flock-based, non-blocking).
- [X] T003 Add `asdd/version_check.py` skeleton with the `VersionCache` reader/writer (5-minute TTL).
- [X] T004 [P] Add `asdd/banner.py` skeleton with `BannerLine` dataclass + `render()`.
- [X] T005 [P] Test files created and populated (skipped the "empty file" intermediate step).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared core that every user story uses. No user story work begins until this phase is complete.

- [X] T006 Implement `asdd/tool_manifest.py:load` reading the on-disk JSON and rejecting unknown `schema_version`.
- [X] T007 Implement `asdd/tool_manifest.py:save` writing atomically and validating invariants.
- [X] T008 [P] Implement `asdd/tool_manifest.py:acquire_lock` using `fcntl.flock(LOCK_EX | LOCK_NB)`.
- [X] T009 [P] Implement `asdd/version_check.py:VersionCache.get/set` (atomic JSON writes).
- [X] T010 [P] Implement `asdd/version_check.py:check_latest` + `check_all` (parallel, cached).
- [X] T011 [P] Implement `asdd/banner.py:render` (alphabetical sort, ≤ 78 cols, summary-fold > 5 stale).
- [X] T012 [P] Implement `asdd/banner.py:should_color` honoring `NO_COLOR` and TTY check.
- [X] T013 Unit tests `tests/unit/test_tool_manifest.py` (12 tests passing).
- [X] T014 [P] Unit tests `tests/unit/test_version_check.py` (8 tests passing).
- [X] T015 [P] Unit tests `tests/unit/test_banner.py` (9 tests passing).

**Checkpoint**: Foundation green; ready to implement user stories.

---

## Phase 3: User Story 1 — Upgrade a tool in a running container with one command (Priority: P1) 🎯 MVP

**Goal**: `asdd upgrade claude <project>` installs the latest claude into the project's overlay in under 30 s without disturbing the persistent Claude session.

**Independent Test**: With a running `asdd serve dev` mid-conversation, run `asdd upgrade claude dev`. `claude --version` inside the container reports the new version; the tmux session keeps running; the conversation history is intact.

### Implementation for User Story 1

- [X] T016 [US1] `asdd/tools.py:NpmGlobalDriver` — `installed_version` (reads aggregate symlink), `latest_version` (npm registry dist-tags), `install` (docker-exec npm install with `--prefix`), `uninstall`. Atomic incoming/→versions/ rename. Injectable `_ContainerRunner` for tests.
- [X] T017 [US1] `asdd/project_container.py:bind_mount_for_tools` returning `(host, container)`; wired into `_compose_mounts` so every new container gets `/home/asdd/.asdd-tools/`.
- [X] T018 [US1] `asdd/bootstrap.py:cmd_upgrade` orchestrator implemented end-to-end: lock → manifest load → version check → driver install → symlink retarget → manifest write → history truncate + evicted-version uninstall → upgrade.log append.
- [X] T019 [US1] CLI `asdd upgrade <tool> <project_id> [--reload] [--json]` translates errors to exit codes 1/2/3/4.
- [X] T020 [P] [US1] `asdd/tools.py:retarget_bin_symlink` — atomic ln-sfn via tmp + os.replace.
- [X] T021 [US1] Dockerfile updated: gh + uv + claude install to `/opt/asdd-baseline/`; overlay-first PATH set on the `asdd` user.
- [X] T022 [US1] Baseline-version snapshots written at build time for claude/gh/uv at `/opt/asdd-baseline/versions/<tool>`.
- [X] T023 [US1] Unit tests for NPM driver: 14 spec-002 tests in `test_bootstrap_upgrade.py` exercise install/no-op/eviction/rollback/pin/unpin/reset/versions.
- [X] T024 [US1] `test_bootstrap_upgrade.py` covers happy path, no-op when current, pin violation, unknown tool, registry unreachable, eviction.
- [X] T025 [US1] `asdd/project_container.py:bounce_persistent_claude` — `tmux kill-window -t asdd:0`; returns True/False.
- [X] T026 [US1] `cmd_upgrade --reload` calls `bounce_persistent_claude` post-install.
- [ ] T027 [US1] **Deferred** — Integration test against a real Docker container. The host this code was written in can't run Docker (sandboxed), so this MUST be run on the operator's Mac after pulling. Skeleton: build image, start container, run `asdd upgrade claude <project>`, assert in-container `claude --version` matches new version, assert manifest shape on host.

**Checkpoint**: US1 fully functional. Running `asdd upgrade claude dev` works against a real container; tests cover the success + failure paths.

---

## Phase 4: User Story 2 — Upgrades survive container recreation (Priority: P1)

**Goal**: After `asdd stop <id>` + `asdd serve <id>` (or any container recreation), upgraded versions are still live.

**Independent Test**: Upgrade `claude`. Stop the container. `asdd serve <id>`. Verify in-container `claude --version` is still the upgraded version.

### Implementation for User Story 2

- [X] T028 [US2] `_compose_mounts` adds the tool overlay mount for EVERY container creation (interactive + persistent + dispatch). All start_container paths share this code.
- [X] T029 [US2] `bind_mount_for_tools` ensures the overlay root exists with 0700 before binding.
- [ ] T030 [US2] **Deferred** (same Docker constraint as T027) — integration test exercising stop + serve cycle.
- [ ] T031 [P] [US2] **Deferred** — doctor check for broken symlinks. Lightweight follow-up; not blocking.
- [ ] T032 [US2] **Deferred** — image-digest mismatch note. Lightweight follow-up.

**Checkpoint**: US2 fully functional. Upgrades survive across recreations and image rebuilds. Doctor surfaces broken symlinks.

---

## Phase 5: User Story 3 — Versions table + session-start banner (Priority: P2)

**Goal**: `asdd versions <project>` shows the table on one screen; `asdd open` / `asdd claude` / `asdd serve` print the banner before attach.

**Independent Test**: Stale claude → banner appears; `asdd versions <project>` shows current + latest + pin.

### Implementation for User Story 3

- [X] T033 [US3] `cmd_versions` implemented: parallel `check_all` + per-tool status (`current`/`update available`/`could not check`/`pinned`); baseline-version fallback when no overlay manifest exists.
- [X] T034 [P] [US3] Status strings + fixed-column table renderer in `_emit_result`.
- [X] T035 [US3] CLI `asdd versions <project_id> [--json]`.
- [X] T036 [US3] Banner integration in `cmd_open` and `cmd_claude` (both the cold-start and persistent-running paths). `print_banner` writes to stderr before attach.
- [X] T037 [US3] `NO_BANNER=1` env var honored in `print_banner`. `--quiet` flag plumb-through deferred to a small follow-up.
- [X] T038 [P] [US3] `test_bootstrap_upgrade.py::test_cmd_versions_marks_update_available` covers the path; `test_stale_tools_for_banner_skips_pinned` covers banner suppression on pins.
- [X] T039 [US3] Banner has dedicated test file (`test_banner.py`, 9 tests).
- [X] T040 [US3] `asdd/tools.py:read_baseline_version` reads `/opt/asdd-baseline/versions/<tool>` via `docker exec cat`.

**Checkpoint**: Operator can see at a glance what's installed + what's available. Banner appears on stale tools and names the action.

---

## Phase 6: User Story 4 — Pinning (Priority: P3)

**Goal**: Lock a project to a specific tool version; bulk upgrades skip pinned tools; single-tool upgrade refuses without explicit override.

**Independent Test**: Pin `claude`; run bulk upgrade; pinned project stays put, others move. Unpin; pinned project then upgrades.

### Implementation for User Story 4

- [X] T041 [US4] `cmd_pin` enforces `current_version == version` else `BootstrapError` → CLI exit 7.
- [X] T042 [US4] `cmd_unpin` is idempotent (no-op on missing pin).
- [X] T043 [US4] `cmd_upgrade` raises `PinViolationError` when pin is set and latest != pin; CLI exits 3.
- [ ] T044 [US4] **Deferred** — bulk `asdd upgrade --all <project>` with confirmation prompt. Skeleton: iterate `TOOLS`, build plan, prompt, then call `cmd_upgrade` per tool.
- [X] T045 [US4] CLI commands `pin` (with `tool=version` arg) and `unpin` wired in. Tests `test_cmd_pin_requires_match` + `test_cmd_unpin_idempotent` cover the unit paths.

**Checkpoint**: US4 functional. Pin/unpin work; bulk upgrade respects pins.

---

## Phase 7: Rollback + Reset (cross-cutting)

**Goal**: `asdd rollback` and `asdd reset-tools` cover the remaining contract surface.

- [X] T046 `cmd_rollback` swaps `history[0]`/`history[1]`, retargets the symlink, appends upgrade.log. Errors `BootstrapError` → CLI exit 6 when nothing to roll back to.
- [X] T047 [P] `cmd_reset_tools` rm-rfs per-tool subdir (or all) + removes aggregate bin symlinks; idempotent.
- [X] T048 Unit tests `test_cmd_rollback_swaps_history` (also verifies symmetric flip), `test_cmd_rollback_no_prior`, `test_cmd_reset_tools_single`, `test_cmd_reset_tools_idempotent`.
- [X] T049 CLI `rollback`, `reset-tools` wired.

---

## Phase 8: Additional tool drivers (Polish)

**Goal**: `gh` and `uv` reach feature parity with `claude`.

- [ ] T050 [P] **Deferred** — `GithubReleaseDriver.install` (tarball download + arch detection + extract). Skeleton + latest_version are in place; install raises "not implemented yet". Roughly ~70 lines of Python + 1 test.
- [ ] T051 [P] **Deferred** — `AstralInstallDriver.install` (downloads uv tarball from astral GitHub releases). Skeleton + latest_version in place. ~70 lines + 1 test.
- [X] T052 Dockerfile installs gh + uv + claude into `/opt/asdd-baseline/`, writes baseline-version snapshots. (Bumped up to T021/T022 since it's all one Dockerfile edit.)
- [ ] T053 [P] **Deferred** — Per-driver unit tests for the two stubs once they're implemented.
- [ ] T054 **Deferred** — gh/uv coverage in the integration test.

---

## Phase 9: Documentation

- [ ] T055 [P] **Deferred** — `USER_GUIDE.md` "Keep your tools current" section.
- [ ] T056 [P] **Deferred** — top-level `README.md` subcommand list.
- [ ] T057 [P] **Deferred** — `TRANSFER.md` follow-ups review.
- [X] T058 CLAUDE.md SPECKIT block points at `specs/002-in-container-tool-upgrades/plan.md`.

---

## Phase 10: Production validation

- [ ] T059 **Deferred** — Operator runs quickstart §7 scenarios end-to-end against a real container.
- [ ] T060 **Deferred** — Performance gate measurement on a real Mac.
- [X] T061 Full `pytest tests/unit/` suite passes — **161/161 green** (118 pre-existing + 43 new from spec 002).
- [ ] T062 **Deferred** — Operator builds `docker build --no-cache -f docker/Dockerfile.project -t asdd/project:latest .` on a Docker-capable host.

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1** → no deps.
- **Phase 2** → depends on Phase 1.
- **Phase 3 (US1, P1)** → depends on Phase 2.
- **Phase 4 (US2, P1)** → depends on Phase 3 (uses the same overlay code).
- **Phase 5 (US3, P2)** → depends on Phase 2 (version-check + banner foundation).
- **Phase 6 (US4, P3)** → depends on Phase 3 (extends cmd_upgrade).
- **Phase 7** → depends on Phase 3 (uses manifest history).
- **Phase 8** → depends on Phase 3 (mirrors the npm driver shape).
- **Phase 9** → depends on the implementation being correct; can start once Phase 3 is green.
- **Phase 10** → final.

### Parallelism within phases

- T004 / T005 in Phase 1 are `[P]` (different files).
- T008–T015 in Phase 2 are mostly `[P]` (different files, no shared mutable state).
- T020 in Phase 3 is `[P]` with T021/T022 (different files).
- T038 / T039 in Phase 5 `[P]`.
- T050 / T051 / T053 in Phase 8 `[P]`.
- T055–T057 in Phase 9 `[P]`.

### MVP path

Phase 1 → Phase 2 → Phase 3 = a working `asdd upgrade claude <project>` against a real container. Could ship here. Phase 4 makes it permanent; Phase 5 makes it discoverable; Phase 6/7 round out the contract; Phase 8 brings the other tools in.

### Suggested MVP scope

T001–T027 (Phases 1–3) — the operator can upgrade claude in a running container with one command. Everything else is incremental on top.

---

## Notes

- All Python new code targets Python 3.12 (matches existing `pyproject.toml`).
- Use `subprocess.run(..., check=False)` and inspect `returncode` — never `check=True` (we want structured exit codes, not exceptions).
- All file writes to the overlay are atomic (`tmp` + `rename`).
- All log lines (stderr) use a consistent `asdd: ` prefix for grep-ability.
- The `--json` flag, where supported, emits exactly one JSON object on stdout — no trailing newlines, no banner contamination.
