# Feature Specification: Container shell vs. Claude entry points, container-aware prompt, preinstalled `gh`

**Feature Branch**: `001-container-shell-and-gh`

**Created**: 2026-06-11

**Status**: Draft

**Input**: User description: "I need to be able to login to the container and get a regular shell, now if I login with `asdd open containerName` I get straight to claude, and if I exit claude I exit the container too. I think the cli command should be: `asdd claude container` takes me to claude, and `asdd open containerName` takes me to the shell. The shell prompt should show the container name. I also want `gh` to be installed when making a new container."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Open a shell in a project container without entering Claude (Priority: P1)

The operator runs `asdd open <project>` and lands at an interactive bash prompt inside the project's container. They can run any command (git, ls, gh, asdd, etc.). Typing `exit` returns them to the host shell and the container is stopped. They never see a Claude prompt and Claude never starts as part of this flow.

**Why this priority**: This is the operator's normal "let me poke around" workflow. Without it, every container-entry is hijacked into a Claude session and the operator can't run plain shell work. P1 because the current behavior the user describes — `asdd open` dropping them into Claude — makes the platform actively painful for everything that isn't a Claude conversation.

**Independent Test**: From the host, run `asdd open <project>`. Confirm that the first prompt is a bash prompt, not Claude's TUI. Type `echo $SHELL` and `id` — both should respond as a shell would. Confirm Claude has not been started by checking `pgrep -fl claude` from within the shell shows nothing related to a running Claude TUI. Typing `exit` returns to the host. Value: the operator can use the container as a normal Linux container.

**Acceptance Scenarios**:

1. **Given** a registered project that is not currently running, **When** the operator runs `asdd open <project>`, **Then** they land at a bash prompt inside the container with no Claude process having been started.
2. **Given** the operator is at the shell prompt from scenario 1, **When** they type `exit`, **Then** they return to the host shell and the container stops cleanly (no orphaned container is left running).
3. **Given** a project whose container is already running in interactive mode, **When** the operator runs `asdd open <project>` again, **Then** the existing behavior of refusing or re-attaching (whichever asdd already does for the duplicate-open case) is preserved — nothing about that contract changes.
4. **Given** the operator is at the shell prompt, **When** they manually run `claude` from that shell, **Then** Claude starts and, when they exit Claude, control returns to the shell prompt (NOT to the host); the container keeps running until the shell itself exits.

---

### User Story 2 - Start a Claude session in a project container via a dedicated command (Priority: P1)

The operator runs `asdd claude <project>` and lands directly in a Claude Code session attached to that project, with all the same auth, mounts, and environment Claude gets today. When they exit Claude, the container stops (matching today's "the session ends with Claude" semantics from `asdd open`).

**Why this priority**: P1 because once `asdd open` no longer launches Claude (User Story 1), the operator still needs a one-command way to start a Claude session — that is the bread-and-butter workflow the platform exists for. Without User Story 2, every Claude session would require two manual steps (`asdd open` then `claude`), regressing on UX.

**Independent Test**: From the host, run `asdd claude <project>`. Confirm Claude starts inside the project's container with the project's auth/mounts intact (e.g., the credential store at `$ASDD_HOME/_state/claude-auth/` is visible to Claude). Exit Claude — control returns to the host and the container stops. Value: one command, same Claude experience as today.

**Acceptance Scenarios**:

1. **Given** a registered project that is not currently running, **When** the operator runs `asdd claude <project>`, **Then** Claude starts inside the project's container and the operator interacts with it as today.
2. **Given** Claude is running from scenario 1, **When** the operator exits Claude, **Then** they return to the host shell and the container stops (matching today's interactive-mode contract).
3. **Given** a persistent session (`asdd serve`) is running for this project, **When** the operator runs `asdd claude <project>`, **Then** the existing attach-to-persistent-session behavior is preserved — `asdd claude` re-attaches to the running session rather than starting a second Claude.
4. **Given** the project has no Claude subscription auth set up, **When** the operator runs `asdd claude <project>`, **Then** they see the same auth error today's `asdd open` would surface (this command does not weaken the auth gate).

---

### User Story 3 - Shell prompt shows which project's container I'm inside (Priority: P2)

When the operator is at a shell prompt inside a project container (whether reached via `asdd open`, manually shelled into, or `docker exec`'d into), the prompt visibly includes the project's identifier so they can tell at a glance which container they're in. The default prompt for the in-container user is updated so the project name appears as part of `PS1`.

**Why this priority**: P2 because it's a quality-of-life improvement that compounds with User Story 1 — once shells are routine again, conflating two open shells across two different projects becomes a real source of mistakes. Less critical than the entry-point split itself, so it ships right after.

**Independent Test**: Open shells in two different project containers in two terminals. Each prompt unambiguously identifies which project that shell is inside. No project name leaks into shells on the host. Value: the operator can confidently tell which container any given shell belongs to.

**Acceptance Scenarios**:

1. **Given** the operator runs `asdd open my-project`, **When** they see the first prompt, **Then** the prompt contains the literal string `my-project` (the project identifier asdd uses elsewhere) in a position that is immediately visible without scrolling.
2. **Given** the operator is shelled into one project's container, **When** they spawn a sub-shell (`bash`), **Then** the project name is still visible in the sub-shell's prompt.
3. **Given** the operator uses `asdd claude <project>` then exits Claude and (per usual flow) ends back on the host, **When** they later `asdd open <project>` to inspect the same container, **Then** the prompt shows the same project name.
4. **Given** the operator is on the host (not inside any asdd container), **When** they see their shell prompt, **Then** no asdd project name leaks into the host prompt.

---

### User Story 4 - `gh` is preinstalled and ready in every new project container (Priority: P2)

Every newly-built project container ships with the GitHub CLI (`gh`) already on `$PATH`, with a recent-enough version that `gh auth login` and standard subcommands work without the operator having to install anything. A first-time operator can open a new project, run `gh auth login`, and immediately push branches and open PRs from inside the container.

**Why this priority**: P2 because operators reach for `gh` constantly (this is a Spec-Driven Development project that produces PRs), and the current container hits the operator with "command not found" the first time. P2 rather than P1 because there is a manual install workaround (the one we used earlier in this session), but it costs ~30 s every fresh container.

**Independent Test**: Build (or rebuild) the project image. Run `asdd open <project>` (per User Story 1). At the shell prompt, run `gh --version` — a sensible version of `gh` is reported. Run `gh auth login`; it walks through the standard device-code flow. Run `gh auth status` after completing the flow — it confirms login. Value: the operator never has to side-install `gh` in a container.

**Acceptance Scenarios**:

1. **Given** a freshly built project image, **When** the operator runs `gh --version` inside the container, **Then** they see a `gh` version, not "command not found."
2. **Given** the operator is at the shell prompt in a fresh container, **When** they run `gh auth login`, **Then** the device-code flow begins and, on completion, `gh auth status` reports them logged in.
3. **Given** `gh` is preinstalled, **When** a new asdd release builds the image on a new architecture (amd64 and arm64), **Then** both architectures end up with a working `gh` binary (no arch-specific blank).
4. **Given** an operator who has an *old* image (built before this feature), **When** they rebuild via the normal asdd image-build path, **Then** they pick up `gh` without any manual steps.

---

### Edge Cases

- **Persistent-session collision with `asdd claude`**: a persistent session (`asdd serve`) is running and the operator runs `asdd claude <project>`. The existing attach-to-persistent-session behavior MUST win; we never start a second Claude in parallel.
- **`asdd open` on an already-running container**: the existing refuse-or-attach behavior MUST be preserved. The shell-vs-Claude split MUST NOT relax the duplicate-open guard.
- **`asdd open` while a persistent session is running**: today this attaches the operator to the persistent session (i.e., to Claude inside tmux). Under this feature, `asdd open` should remain consistent with its new contract: open a shell. If a persistent session is running and the operator wants the session, they use `asdd attach` (which already exists). `asdd open` MUST refuse with a clear message in that case (do not silently re-attach to Claude — that would re-introduce the very surprise we're removing).
- **Exit-on-claude-exit semantics for `asdd claude`**: when Claude exits, `asdd claude` returns the operator to the host and stops the container. This matches today's `asdd open` interactive contract and is what the operator expects.
- **PS1 customization conflict**: the operator (or an in-container tool) overrides `PS1` after login. Project-name visibility MUST be sourced early enough that it is preserved unless the operator deliberately overwrites it later, but MUST NOT fight the operator who explicitly changes their own prompt.
- **`gh` version drift**: `gh`'s minor releases ship frequently. The image MUST pin a known-good version and update it deliberately, not chase HEAD on every build (so a regression in `gh` does not silently break asdd containers).
- **`gh` and the existing Claude auth mount**: `gh`'s config lives at `~/.config/gh`. It MUST NOT collide with the Claude credential store (which lives at `~/.claude` and `~/.claude.json` per spec 009). They occupy different paths, so this is a confirmation, not a change.
- **Existing scripts that call `asdd open` expecting Claude**: any script or doc inside the project skeleton, USER_GUIDE, or CLAUDE.md that documents "`asdd open` drops you into Claude" MUST be updated to reflect the new contract; otherwise operators following old docs will be surprised.
- **`asdd dispatch` and `asdd serve`**: not affected by this feature. Those modes have their own entry points and do not go through `asdd open`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `asdd open <project>` MUST start the project's container in interactive mode and drop the operator at an interactive bash prompt. Claude MUST NOT be started as part of this command.
- **FR-002**: When the operator exits the shell from FR-001, `asdd open` MUST return them to the host shell and stop the container, leaving no orphaned containers.
- **FR-003**: `asdd open` MUST preserve today's safety guard against duplicate opens: if a container is already running for the project in any mode (interactive, dispatch, persistent), `asdd open` MUST refuse with a clear message rather than silently re-attaching to Claude or starting a second container.
- **FR-004**: A new top-level CLI command `asdd claude <project>` MUST exist. It MUST start the project's container and run Claude Code inside it with the same auth, mounts, and environment that today's `asdd open` flow provides.
- **FR-005**: When the operator exits Claude under `asdd claude`, the command MUST return them to the host and stop the container — same contract as today's interactive mode.
- **FR-006**: `asdd claude` MUST detect a running persistent session and re-attach to it (matching today's persistent-session re-attach behavior), rather than starting a second Claude.
- **FR-007**: The in-container bash prompt MUST include the project's identifier (the same string asdd uses for `project_id` elsewhere) so that the operator can identify which container a given shell belongs to. The identifier MUST appear in the prompt without the operator running any extra commands after login.
- **FR-008**: The project-name component of the prompt MUST come from a source the container can resolve at shell start without requiring the operator to set environment variables manually — for example, an env var the asdd CLI passes in, a file under `/etc/`, or another container-internal artifact. The mechanism MUST work for any shell entered via `asdd open`, manual `docker exec`, or a sub-shell spawned inside the container.
- **FR-009**: The default in-container shell configuration MUST set the prompt before the operator gets control, but MUST NOT prevent the operator from overriding `PS1` afterwards.
- **FR-010**: The host operator's shell prompt MUST NOT be modified by this feature.
- **FR-011**: The project container image MUST ship with `gh` (GitHub CLI) preinstalled on `$PATH`, with a version pinned in the Dockerfile and updated only by an explicit change to that pin.
- **FR-012**: The preinstalled `gh` MUST work on both amd64 and arm64 builds of the project image (matching the architectures the rest of the image targets).
- **FR-013**: Documentation that today says "`asdd open` drops you into Claude" — including the user guide, the CLAUDE.md orientation, and the project skeleton's README — MUST be updated to describe the new split (`asdd open` → shell, `asdd claude` → Claude).
- **FR-014**: `asdd dispatch`, `asdd serve`, `asdd attach`, and other non-interactive modes MUST NOT be affected by this feature. Their contracts continue unchanged.

### Key Entities *(include if feature involves data)*

- **CLI command `asdd open`**: existing command. Behavior changes to "interactive shell, no Claude." Argument: `project_id`.
- **CLI command `asdd claude`**: new command. Behavior: "interactive Claude session." Argument: `project_id`. Returns Claude's exit code.
- **In-container shell prompt (`PS1`)**: in-container artifact. Carries the project identifier as a visible component.
- **Project container image (`asdd/project:latest`)**: ships with `gh` preinstalled and the prompt-customization wired into the default shell init.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of `asdd open` invocations in a smoke test land at a bash prompt within 5 seconds of the command being issued, with no Claude process started.
- **SC-002**: 100% of `asdd claude` invocations against a project with valid auth start a Claude session within 5 seconds of the command being issued.
- **SC-003**: 0 cases (in a sample of 20 shell-open events across two different projects) where an operator misidentifies the container they're in — verified by asking a colleague to tell, from looking at the prompt alone, which project each shell is for.
- **SC-004**: In a fresh container, `gh --version` succeeds (exit code 0, version printed) on the first try with no operator setup. Measured: 100% across a clean build on each supported architecture.
- **SC-005**: Time from "fresh project created" to "operator has pushed a branch with `gh`" drops measurably versus today's flow that required side-installing `gh` first. Target: at least 30 seconds faster on a warm cache.
- **SC-006**: 0 orphaned project containers left running after a sample of 20 `asdd open` and 20 `asdd claude` exits.

## Assumptions

- The current `asdd open` implementation already runs `docker exec -it bash` inside an interactive-mode container (per `attach_shell` in `asdd/project_container.py`); the user's reported "lands in Claude" experience reflects a container built before that path was reliable, or a container with an in-image bash init that auto-starts Claude. This feature codifies "shell, never Claude" as the explicit contract regardless of which past state any individual operator has cached.
- The current Dockerfile already installs `gh` (`gh 2.92.0` at the time of writing). This feature keeps that install and treats the requirement as a "do not regress + bump cadence" contract rather than a brand-new addition; the spec is written so future regressions are caught.
- The shell-prompt mechanism is allowed to use either bash's `~/.bashrc`, `/etc/profile.d/`, or an env var set by the asdd CLI when starting the container — the spec does not constrain which, only that the project name MUST end up visible.
- The project identifier passed to `PS1` is the same string asdd uses for `project_id` everywhere else (Docker container name, registry row, etc.) — no new naming scheme is introduced.
- Subscription auth flow for `asdd claude` is identical to today's interactive `asdd open` flow (per spec 009 in the repo's constitution). No new auth surface is added.
- Existing `asdd open` callers in scripts and CI are minimal because the platform is operator-facing and pre-1.0; we accept a one-shot breaking change to `asdd open` semantics and address callers via the documentation FR (FR-013).

## Dependencies

- The asdd CLI (`asdd/bootstrap.py`, `asdd/project_container.py`) is the surface this feature changes; no new infrastructure dependencies are introduced.
- The project container image build pipeline (Docker) must rebuild after the Dockerfile change for new images to pick up the prompt and `gh` pin.
