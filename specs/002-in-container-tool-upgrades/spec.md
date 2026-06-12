# Feature Specification: Convenient & Secure In-Container Tool Upgrades

**Feature Branch**: `002-in-container-tool-upgrades`

**Created**: 2026-06-12

**Status**: Draft

**Input**: User description: "We need to explore rebuild and upgrade to the solution, and have a setup that makes it possible to keep the installed tools updated over time. Goal is to make this convenient and secure without breaking anything."

## Clarifications

### Session 2026-06-12

- Q: Persistence layer scope — per-project, global, or per-project default + opt-in shared? → A: Per-project. Each project gets its own upgrade layer; pins are per-project; one project's upgrade can never affect another.
- Q: When does the system check for updates — manual only, notify on demand, notify at session start, or scheduled silent upgrade? → A: Notify at session start. `asdd open` / `asdd serve` / `asdd claude` does a quick check and prints a one-line banner per out-of-date tool that names the exact command to run. Nothing is upgraded silently.
- Q: How should an upgrade affect a running Claude session (install-only / auto-restart / install-only default + `--reload` flag)? → A: Install-only by default; the operator can pass `--reload` to also bounce the running Claude (supervisor relaunches via `claude --continue` so the conversation resumes in the new version). Without `--reload` the banner names the action to load the new version.
- Q: How many previous tool versions should be retained per project for rollback? → A: 2 — the last two prior versions, oldest evicted automatically.

## Problem Framing

asdd-managed containers ship with operator tools — `claude`, `gh`, `uv`, `npm` packages — baked in at image build time. Today, upgrading any of them is unreasonably painful for a daily workflow:

- **In-container auto-update is broken by file ownership.** `Dockerfile.project` installs `claude` as root under `/usr/local/lib/node_modules/`, but the container runs as user `asdd` (uid 1000) who can't write there. Claude's own self-updater silently fails, printing only `Auto-update failed · Try claude doctor or npm i -g @anthropic-ai/claude-code` in the footer.
- **The fallback is a heavy host-side ritual.** Operators must `docker build --no-cache`, then `docker rm` the running container, then `asdd serve` again — losing any in-flight persistent Claude session in that container in the process.
- **No first-class command exists.** `asdd` exposes no `upgrade`, `rebuild`, or `versions` command. Operators have to remember low-level Docker incantations and the Dockerfile path.
- **The persistent session is fragile under upgrades.** A persistent `asdd serve` session holds an interactive Claude inside tmux. Killing and recreating the container takes that session with it, which is exactly the workflow the operator is trying to protect.

The asymmetry — Claude releases a new version every few days, but upgrading it inside the container takes 5 minutes of careful Docker work — means operators tend to skip upgrades and run stale tools. This silently widens the gap between the tools the company is paying for and what the operator actually uses.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Upgrade a tool in a running container, with one command, without losing the session (Priority: P1)

A daily operator notices a new Claude release is available. They run a single asdd command from their host shell that upgrades `claude` inside the running container; the persistent Claude session keeps running across the upgrade, picks up the new binary on its next prompt cycle, and reports the new version in its footer. No `docker` subcommand is touched.

**Why this priority**: This is the immediate operational pain. Without this, every Claude release puts the operator in a "upgrade now and lose my context, or keep working on a stale binary" trade-off they'll always resolve toward "stale." The single command unlocks the whole workflow.

**Independent Test**: From a Mac shell, with a running persistent `asdd serve <id>` session that's mid-conversation, the operator runs `asdd upgrade claude <id>`. The conversation continues uninterrupted (or with at most a single short prompt to reload). Capturing the tmux pane afterward shows the new Claude version and no loss of conversation history.

**Acceptance Scenarios**:

1. **Given** `asdd serve dev` is running with a Claude conversation in progress, **When** the operator runs `asdd upgrade claude dev`, **Then** the upgrade completes within 30 seconds, `claude --version` inside the container reports the new version, and the tmux Claude session continues running with its conversation history intact.
2. **Given** the same setup as above, **When** the upgrade fails partway through (network error, npm 500, etc.), **Then** the previous `claude` binary remains in place and functional, and the operator sees a clear error message identifying the failure mode.
3. **Given** the operator runs `asdd upgrade claude dev` while no persistent session is running for `dev`, **When** the command executes, **Then** the upgrade is applied to the project's image/persistence layer so that the next `asdd open dev` or `asdd serve dev` uses the new version.

---

### User Story 2 - Upgrades survive container recreation (Priority: P1)

The operator upgrades `claude` in a running container today. Tomorrow they reboot their Mac and the launchd babysitter recreates the container from the asdd image. The `claude` binary in the recreated container is still the upgraded version — they don't have to re-upgrade after every restart.

**Why this priority**: Without this, the convenience of US1 evaporates the first time the container is recreated for any reason — system reboot, image rebuild, `asdd stop` + `asdd serve`. Operators would end up upgrading the same tools repeatedly, eroding trust in the upgrade command.

**Independent Test**: Operator runs `asdd upgrade claude dev`; verifies new version is live; runs `asdd stop dev` then `asdd serve dev`; verifies the new version is STILL live in the freshly-recreated container.

**Acceptance Scenarios**:

1. **Given** an upgraded `claude` is running in container A, **When** A is stopped and `asdd serve` recreates the container as A', **Then** A' starts with the same upgraded `claude` version — without the operator re-running the upgrade command.
2. **Given** the operator rebuilds the asdd image from a freshly-pulled `Dockerfile.project`, **When** containers are recreated from the new image, **Then** the operator's upgraded tool versions take precedence over whatever the rebuilt image's base versions would have been (unless the image's version is newer).
3. **Given** the operator deliberately wants to reset to image baseline, **When** they run a clearly-named reset command, **Then** the persistent upgrade layer for that project is cleared and the next container starts at the image baseline.

---

### User Story 3 - See what's installed, what's available, in one screen (Priority: P2)

Before deciding whether to upgrade, the operator wants to see what's installed and whether anything is out of date. A single command shows a table of every managed tool: current version inside the container, latest published version, and a clear marker on rows that are out of date.

**Why this priority**: Convenience layer on top of US1. Without it, the operator has to remember tool names, run `--version` for each, and check release pages manually. With it, the upgrade decision becomes "I see two rows are out of date, run `asdd upgrade --all dev`." Important but not blocking — US1 + US2 deliver value on their own.

**Independent Test**: Operator runs `asdd versions dev` (or equivalent). Output lists every managed tool with current + latest, marks out-of-date rows, and fits on a normal terminal screen.

**Acceptance Scenarios**:

1. **Given** `claude` is one version behind, **When** the operator runs the versions command, **Then** the `claude` row shows the installed version, the available newer version, and a clear "update available" marker.
2. **Given** all tools are current, **When** the operator runs the versions command, **Then** the table shows all rows with no update markers and a short "all current" summary line.
3. **Given** the operator is offline or the upstream package registry is unreachable, **When** they run the versions command, **Then** current versions still appear and the "latest" column shows a clear "could not check" indicator per row — not a hard error.

---

### User Story 4 - Pin a tool to a specific version for a project (Priority: P3)

For a specific project where reproducibility matters (a long-running playtest, a published bot, a regulated workflow), the operator pins `claude` to a specific version. From that point on, automatic upgrade flows skip that tool in that project; explicit upgrade commands warn the operator before overriding the pin.

**Why this priority**: Reproducibility insurance. Not every operator needs it, but anyone with a project that's been quietly working for months wants the option to say "don't touch this." Lower priority because most projects benefit from running latest.

**Independent Test**: Operator pins `claude` to version X in project P. They run a bulk upgrade across all projects. Project P's `claude` remains at version X; other projects are at the latest. They unpin and re-run; project P picks up latest.

**Acceptance Scenarios**:

1. **Given** the operator has pinned `claude` at v2.1.150 for project `td`, **When** they run `asdd upgrade --all`, **Then** every other project's `claude` upgrades to the latest version and `td` stays at v2.1.150.
2. **Given** the operator runs `asdd upgrade claude td` against a pinned tool, **When** the command executes, **Then** it surfaces the pin, asks for confirmation (or requires a `--force` flag), and respects the operator's response.
3. **Given** the operator pins to a version that no longer exists upstream, **When** they `asdd serve` that project, **Then** they get a clear error pointing at the pin and how to amend it.

---

### Edge Cases

- **Mid-upgrade container restart**: The container is restarted by launchd while an upgrade is mid-flight (npm download partway done). On restart, the container MUST come up in either the old or the new version — never a half-installed broken state.
- **Persistent session has the old binary loaded**: A long-running `claude` process inside the persistent session is the previous version. The upgrade replaces the binary file, but the running process keeps its in-memory image. The system MUST either (a) reload the running process safely, or (b) clearly state that the next prompt cycle / next `claude` invocation will use the new version, without surprising the operator.
- **Concurrent upgrades**: Two terminal windows run `asdd upgrade claude dev` at the same time. The system MUST serialize cleanly — one wins, the other reports "already in progress" — never racing into a corrupt install.
- **Image baseline ahead of pinned version**: The image was rebuilt with a newer `claude` than a project's pin. The system MUST honor the project's pin and surface a one-line note ("project pin is older than image baseline; using pinned version").
- **Upgrade introduces an incompatibility**: The new tool version breaks something the operator was relying on. They MUST be able to roll back to the previous version with one command.
- **Tool installed multiple ways**: A tool exists both as an apt package and as an npm package. The system MUST own exactly one install path per tool and not let the two diverge silently.
- **Disk pressure**: Frequent upgrades accumulate old versions in the persistence layer. The system MUST cap the number of retained prior versions and clean up automatically.
- **Network down at upgrade time**: Registry / GitHub / apt mirror is unreachable. The current binary stays in place; the upgrade reports the network failure clearly without leaving partial files.
- **Project never started before upgrade**: The operator runs an upgrade for a project that has never had a container created. The system MUST defer the upgrade to first-start rather than fail, OR refuse with a clear message naming the missing prerequisite.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Operators MUST be able to upgrade a single named tool inside a single project with one command from their host shell. The command MUST NOT require any `docker` subcommand to be remembered.
- **FR-002**: The upgrade command MUST run successfully against a project that has a persistent Claude session in progress, without dropping the conversation, without forcing a container recreate, and without requiring the operator to detach from anything.
- **FR-003**: The upgrade MUST persist across container restarts triggered by the launchd babysitter (i.e., the in-container changes survive a Docker `restart` of the same container).
- **FR-004**: The upgrade MUST persist across container *recreation* — when the operator stops the container and `asdd serve` creates a new one, the new container MUST start with the upgraded versions, not the image baseline.
- **FR-005**: The upgrade MUST persist across *image rebuild* — after the operator builds a new asdd image (e.g., to pick up a Dockerfile change), the operator's upgraded versions MUST continue to take precedence over the rebuilt image's baseline versions for that tool, unless the image's version is newer.
- **FR-006**: A bulk-upgrade command MUST exist that upgrades every managed tool to the latest available version in one invocation, with a single confirmation prompt summarizing what will change.
- **FR-007**: A "versions" command MUST list every managed tool with its currently-installed version and (when reachable) the latest published version, fitting on one terminal screen for the common case of fewer than ~20 tools.
- **FR-008**: An upgrade MUST be atomic from the operator's perspective: either the new version is live or the old version is still live; the system MUST NOT leave a half-installed state visible to the operator.
- **FR-009**: A failed upgrade MUST leave a clear error message naming the failing step and the tool, AND leave the previous binary in place and functional.
- **FR-010**: The system MUST NOT require the container to run as root permanently. Any root operation required for upgrades MUST be scoped to the upgrade step itself (e.g., a short-lived elevated exec) or removed by changing where tools are installed.
- **FR-011**: Operators MUST be able to roll back the most recent upgrade for a given tool in a single command. The system MUST retain the **last two prior versions** per tool (cap = 2); older targets are evicted automatically.
- **FR-012**: Each project MUST be able to *pin* a tool to a specific version. Pinned tools MUST be skipped by bulk-upgrade flows and MUST require explicit override on single-tool upgrade flows.
- **FR-013**: A *reset* command MUST exist that clears the project's upgrade persistence layer for one tool or for all tools, returning the project to its image baseline on next container start.
- **FR-014**: The default `asdd upgrade <tool> <project>` invocation MUST install the new binary without disturbing any running long-lived process. For the common Claude case, the running Claude continues to use the old version in-memory; the system MUST surface this in the versions command output and in the upgrade-success message, naming the exact action that loads the new version (e.g., "Claude will pick up the new version after `/clear` or on next session start"). When the operator passes `--reload`, the system MUST additionally bounce the running Claude such that the supervisor relaunches it via `claude --continue` — conversation resumes in the new version within a brief reconnect.
- **FR-015**: The system MUST cover the full set of operator-facing tools currently in `Dockerfile.project` (today: `claude`, `gh`, `uv`, anything else installed by npm or apt during image build), not just `claude`. Other tools added later MUST be coverable by a single, documented additional entry — not an architectural change.
- **FR-016**: Upgrades MUST be applied only on explicit operator command — never silently in the background. The system MUST, however, perform a quick "is anything out of date?" check at session start (on `asdd open`, `asdd serve`, and `asdd claude` invocations) and, for each tool that has a newer version available, print a one-line banner that includes the exact command the operator can run to apply the upgrade (e.g., `claude 2.1.151 available — run \`asdd upgrade claude <id>\` to apply`). The banner MUST appear before the session attaches so the operator sees it without scrolling.
- **FR-018**: The session-start update check MUST NOT block session start. If the upstream registry is unreachable or slow, the check MUST time out within a documented short interval (e.g., 2 seconds per tool) and the session MUST attach normally — the operator never waits on the network to start working.
- **FR-017**: Upgrade persistence MUST be per-project. Each project carries its own upgrade layer keyed off its `$ASDD_HOME` (or equivalent project identifier). An upgrade applied in project A MUST NOT affect the installed versions in project B, even though both containers are built from the same image baseline.

### Key Entities

- **Managed tool**: A named binary the system knows how to upgrade. Carries: tool name, install method (npm-global, apt, pipx, uv, etc.), source registry, optional pinned version, optional roll-back target version, currently-installed version.
- **Upgrade plan**: A snapshot of (tool, from-version, to-version) tuples the system proposes to apply. Surfaced by the versions command for review and by upgrade commands for confirmation.
- **Persistence layer**: The location where upgraded tool binaries live so they survive container restarts/recreation/image rebuilds. Each project has its own slice. The layer MUST be backup-friendly (the operator can copy it elsewhere) and inspectable from the host.
- **Pin**: A per-project, per-tool fixed version that overrides automatic upgrade flows. Surfaced in the versions command output.
- **Rollback target**: The previous version of a tool, retained for the rollback command. Capped at a documented number per tool.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can upgrade `claude` in a running container in under 30 seconds from typing the command to seeing the new version reported by the tool's own `--version` flag.
- **SC-002**: A persistent Claude session that was mid-conversation when the upgrade started survives the upgrade with zero loss of conversation history.
- **SC-003**: The operator does not need to type any `docker` subcommand, edit any Dockerfile, or remember any image tag to perform an upgrade.
- **SC-004**: After a full container recreation (the operator runs `asdd stop <id>` followed by `asdd serve <id>`), the upgraded tool versions are still live with zero additional operator action.
- **SC-005**: After a full image rebuild (the operator runs the image rebuild command and recreates the container), the upgraded tool versions are still live with zero additional operator action, unless the image baseline now ships a newer version.
- **SC-006**: A single `asdd versions` command shows every managed tool's current + latest version on one terminal screen for the typical case of fewer than 20 tools.
- **SC-007**: At least 90% of upgrade attempts complete successfully on first run without operator intervention (no manual retry, no follow-up commands), measured across operator sessions in a normal four-week window after the feature ships.
- **SC-008**: Zero recorded incidents of a persistent Claude session being terminated as a side-effect of an upgrade command, in the same four-week window.
- **SC-009**: An operator who has never used the feature before can read its help text and complete a successful upgrade within five minutes, without consulting external documentation.

## Assumptions

- The asdd Dockerfile, container layout, persistent-session supervisor, and auth-mount conventions remain as they are today (specs 008–010). This feature adds an upgrade surface on top of them; it does not redesign them.
- Containers run as user `asdd` (uid 1000) and most tools are installed at image-build time. Some tools (like `claude`) ship their own self-updater that we want to make work properly; others (like apt-installed binaries) need an asdd-level upgrade command since they have no self-updater.
- All managed tools have a single, well-defined upstream source (npm registry, GitHub releases, apt repository). Tools without a stable upstream are out of scope for this feature.
- Disk usage from retained rollback targets is acceptable when capped at a documented small number (e.g., last two prior versions per tool).
- The host is a single operator's Mac. Multi-operator / multi-host coordination is out of scope.
- Automatic upgrade scheduling, if adopted, runs from the existing launchd babysitter or via a small new agent; introducing a new always-running daemon outside that pattern is out of scope.
- Tools installed for development of asdd itself (Python deps in `pyproject.toml`, test infrastructure) are out of scope; this feature is about the *operator-facing* tools inside per-project containers.
- The feature MAY require changes to `Dockerfile.project` to change install paths or permissions; the constitution's Container-Portable Runtime principle (no host-OS-specific facilities) MUST still be honored.

## Out of Scope

- Multi-host coordination (syncing upgrades across two operators' Macs).
- Tools NOT in `Dockerfile.project` (operator's host tools, asdd's Python dependencies).
- A web UI or dashboard for the versions table. CLI-only.
- A package mirror or offline cache; the feature assumes the operator has internet at upgrade time.
- Replacing Claude's own auto-updater with an asdd-managed mechanism. Where Claude has a working updater, we make it work; we don't reinvent it.

## Open Questions for `/speckit-clarify`

These are the decisions the planner should resolve before implementation. Listed here for visibility; they also appear inline as `[NEEDS CLARIFICATION]` markers.

1. ~~**Automatic vs manual upgrades** (FR-016)~~ — **Resolved 2026-06-12**: notify at session start with an actionable command hint; never silent.
2. ~~**Per-project vs global upgrade layer** (FR-017)~~ — **Resolved 2026-06-12**: per-project.
3. ~~**Rollback retention depth.**~~ — **Resolved 2026-06-12**: 2 prior versions per tool.
4. ~~**In-place reload of running Claude** (FR-014 edge)~~ — **Resolved 2026-06-12**: install-only by default; `--reload` flag bounces the running Claude (supervisor resumes via `claude --continue`).
