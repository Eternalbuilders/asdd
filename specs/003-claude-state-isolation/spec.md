# Feature Specification: Per-project Claude state isolation under the shared auth store

**Feature Branch**: `003-claude-state-isolation`

**Created**: 2026-06-12

**Status**: Draft

**Input**: User description: "Per-project Claude state isolation under the shared auth store. Spec 009 mounts the shared auth store onto ~/.claude/ in every project container, sharing not just the OAuth credential file but everything under ~/.claude/: conversation transcripts, auto-memory, todos, shell-snapshots, statsig, ide. Compounded by the fact that every container uses the same in-container workdir, every project's Claude session collides on the same per-project state directory. Net effect: starting a fresh container for project B replays project A's transcripts, surfaces A's auto-memory, and can resume into A's history. Goal: each project's Claude per-project state is isolated to that project's container, while OAuth credentials and account config remain shared from a single asdd-owned store (spec 009 intent preserved)."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Project A's session history does not leak into Project B (Priority: P1)

The operator has two host projects, P_a and P_b, each with its own asdd-managed container. They use Claude in P_a — sending messages, accumulating conversation transcripts, building up auto-memory specific to P_a, and writing shell snapshots. Later, in a fresh shell, they start P_b's container and launch Claude. They expect a clean session for P_b: no echo of P_a's last conversation, no auto-memory entries written by P_a's sessions, no completed-todo cruft from P_a, no shell snapshots from P_a. The two projects' Claude states are independent.

**Why this priority**: This is the regression the user reported in production on 2026-06-12. Cross-project transcript leakage is a privacy issue (conversation content from one client's work surfacing in another's session is unacceptable), a correctness issue (Claude's auto-memory derives behavioural rules from the wrong project's history), and a usability issue (operators cannot trust what they see in a fresh container). No other story matters until this one is delivered.

**Independent Test**: Two containers for two distinct projects. In project A, run a Claude session that writes content to its per-project state (a one-line conversation will populate `projects/<slug>/*.jsonl`; saving an auto-memory entry will create `projects/<slug>/memory/MEMORY.md`). In project B, inspect the same in-container paths and confirm none of A's content is present. Conversely, content written from B is absent in A.

**Acceptance Scenarios**:

1. **Given** the operator has run a Claude session in project A's container that produced conversation transcripts under that container's `~/.claude/projects/`, **When** they later start project B's container and inspect `~/.claude/projects/`, **Then** none of A's transcripts are visible.
2. **Given** the operator has saved an auto-memory entry while working in project A, **When** they start Claude in project B's container, **Then** that memory entry does not appear in project B's auto-memory.
3. **Given** the operator has accumulated todos and shell snapshots in project A's container, **When** project B's container starts, **Then** project B's `~/.claude/todos/` and `~/.claude/shell-snapshots/` show only what project B's own sessions have produced.

---

### User Story 2 — One login serves every project, and a token refresh in one is visible in all (Priority: P1)

The operator runs `asdd login` once. Every subsequent project container — current and future — authenticates against that same login without re-prompting. When a session in project A refreshes the OAuth token (Claude does this transparently), the next container start in project B uses the refreshed token, not a stale copy. The operator never sees "you need to re-login" when switching between projects.

**Why this priority**: Preserving the spec 009 invariant ("Subscription auth is the default for all modes" via a single shared credential store) is the whole reason this fix is structural rather than just "stop sharing `~/.claude/`". If isolation accidentally split credentials per project, every new project would prompt for a fresh login — a regression of equal weight to the leakage in Story 1.

**Independent Test**: Run `asdd login` once. Start a container for project A and confirm Claude authenticates without prompting. Start a container for project B and confirm Claude authenticates without prompting. Force a token refresh in A (e.g. wait past the access-token TTL, or modify the credential file's expiry), confirm B picks up the refreshed credential on next start without an interactive prompt.

**Acceptance Scenarios**:

1. **Given** the operator has logged in once via `asdd login`, **When** they start a container for any project, **Then** Claude in that container authenticates without prompting.
2. **Given** a session in project A refreshes the OAuth token during normal use, **When** the operator next starts project B's container, **Then** project B authenticates with the refreshed token without prompting.
3. **Given** the operator runs `asdd logout`, **When** they start any project's container afterward, **Then** Claude prompts for login (the shared credential is gone for everyone).

---

### User Story 3 — Project lifecycle cleans up per-project Claude state (Priority: P2)

When the operator removes a project from asdd's management (via the existing project-lifecycle command), all of that project's accumulated Claude per-project state — transcripts, memory, todos, snapshots — is removed alongside the container. The operator does not have to remember to clean up a second location; deleting the project deletes everything connected to it.

**Why this priority**: P2 because the user's first-day experience does not depend on it (Story 1 alone is enough to ship), but skipping it leaves a tail of accumulating orphan state under `$ASDD_HOME/_state/` that nobody cleans up. Important enough that it has to be part of this feature, not a later cleanup task.

**Independent Test**: Create a project, run a Claude session that produces visible per-project state on the host, then remove the project. Confirm the per-project state directory for that project is gone, and that no other project's state was touched.

**Acceptance Scenarios**:

1. **Given** project A has accumulated per-project Claude state on the host, **When** the operator removes project A through the existing project-lifecycle command, **Then** A's per-project Claude state directory is removed.
2. **Given** projects A and B both exist, **When** the operator removes project A, **Then** project B's per-project Claude state is untouched.

---

### User Story 4 — Upgrading operators are not caught by silent migration (Priority: P2)

An existing operator upgrades asdd. Their old shared store has already accumulated mixed conversation history from many projects (the bug being fixed). After the upgrade, starting a project container does not silently move, copy, or delete that accumulated mixed history into any single project's per-project tree (it would be ambiguous which project owns what), nor does it silently erase it. Instead, the operator is informed once — clearly enough to act if they want a clean slate — and the new isolation behaviour begins for fresh state from that point forward.

**Why this priority**: P2 because a fresh installation does not need this story at all; only the existing user — currently one person, the user reporting the bug — needs it. Important because silently destroying their accumulated history (or silently keeping it visible across projects after the upgrade) would each be bad outcomes. The operator needs to be in control of the migration moment.

**Independent Test**: Stand up a state directory mimicking the pre-upgrade layout (mixed transcripts in the shared store). Run the upgraded asdd. Confirm: nothing is silently deleted, no project's per-project tree silently inherits the mixed history, and the operator is shown a one-time notice describing the situation and the recommended action.

**Acceptance Scenarios**:

1. **Given** an upgraded asdd installation with pre-existing mixed per-project state in the old shared location, **When** the operator starts a project container for the first time after the upgrade, **Then** the old mixed state is left in place (not silently consumed by this project, not silently deleted) and a one-line notice describes the situation and the recommended remediation.
2. **Given** the operator follows the notice's recommended remediation (a clean `asdd logout` followed by `asdd login`), **When** they next start a project container, **Then** all accumulated mixed state is gone and the new isolated layout is in effect.

---

### Edge Cases

- **Throwaway login container.** The interactive-login flow uses a transient container with no project association. The shared credential mounts apply normally; any per-project state the login flow happens to write is ephemeral by definition (the container is `--rm`).
- **Persistent-supervised session (spec 010).** A long-lived project container with `claude --continue` semantics must, by design, see its own per-project transcript history across restarts. The per-project state directory must persist and be the one the supervised container sees on every restart.
- **Two operators (one host) using `asdd` for distinct projects.** Out of scope: asdd is a single-operator tool; the credential store is host-scoped, not user-scoped.
- **Concurrent containers for the same project.** Two simultaneous containers for the same project would share the per-project state directory by design (it is the project's state). They would also race on transcript writes the same way two host-side Claude processes would; this is not a new failure mode.
- **Credential file rewritten in place vs. replaced.** A token refresh may rewrite the credential file in place or atomically replace it (write+rename). The chosen mounting approach must survive either pattern without an operator-visible auth failure.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Each project's container MUST expose only that project's per-project Claude state (conversation transcripts, auto-memory, todos, shell-snapshots, IDE state, statsig) under `~/.claude/`. No other project's per-project state is visible.
- **FR-002**: All project containers MUST authenticate against a single shared credential surface. One `asdd login` serves every project.
- **FR-003**: An OAuth token refresh that occurs during a session in one project MUST be visible to every other project on its next container start, without re-prompting the operator.
- **FR-004**: Each project's per-project Claude state MUST persist across that project's container restarts. The persistent-session mode (spec 010) MUST see its own accumulated transcripts across restart cycles.
- **FR-005**: Removing a project through asdd's existing project-lifecycle command MUST remove that project's per-project Claude state directory. No other project's state is affected.
- **FR-006**: `asdd logout` MUST remove both the shared credential surface and every project's per-project Claude state directory. After logout, any subsequent container start requires a fresh login.
- **FR-007**: All per-project Claude state MUST be stored within `$ASDD_HOME`. It MUST NOT travel in a project workspace clone, archive, or any artifact extracted from a project workspace.
- **FR-008**: Per-project state directories and the shared credential surface MUST be created with permissions that prevent other host users from reading their contents.
- **FR-009**: Upgrading from a prior asdd version that accumulated mixed per-project state in the old shared location MUST NOT silently delete that state, MUST NOT silently inherit it into any one new per-project tree, AND MUST surface a one-time operator-facing notice describing the situation and the recommended remediation.
- **FR-010**: The throwaway interactive-login container (which has no project association) MUST continue to authenticate against the shared credential surface using the existing flow; any per-project state it writes is ephemeral.
- **FR-011**: A new per-project state directory MUST be materialised before the project's container first starts, so the in-container Claude session has an initialised state surface from the first invocation.

### Key Entities

- **Shared credential surface**: The single asdd-owned set of files that hold OAuth credentials and account configuration. Mounted into every project's container; managed by `asdd login` / `asdd logout`. Identical content in every container.
- **Per-project state directory**: A per-project asdd-owned directory holding everything Claude writes under `~/.claude/` that is not credentials: conversation transcripts, auto-memory, todos, shell-snapshots, IDE state, statsig. One per project; bound to the project's lifecycle.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: When the operator finishes a Claude session in one project and starts a fresh container for a different project, zero per-project artifacts (conversation transcripts, auto-memory, todos, shell snapshots) from the first project are visible in the second.
- **SC-002**: After a single `asdd login`, the operator can start containers for an unlimited number of distinct projects with no additional login prompts within the credential lifetime.
- **SC-003**: An OAuth token refresh that occurs in one project's container is picked up by 100% of other projects' containers on their next start, with no interactive prompt.
- **SC-004**: Removing a project from asdd's management removes 100% of that project's accumulated Claude per-project state within the same operation.
- **SC-005**: An upgraded operator (whose state predates this fix) is shown a single, clear notice about migration on their first post-upgrade container start, and never sees the same notice twice.
- **SC-006**: The persistent-session mode resumes from its own project's transcripts (and only its own) across an arbitrary number of supervisor-driven restarts.

## Assumptions

- The Claude Code distribution writes per-project state under `~/.claude/` in well-known subdirectories (`projects/`, `todos/`, `shell-snapshots/`, `statsig/`, `ide/`) and rewrites or refreshes the credential file in a way that survives a bind-mounted target (in-place write or atomic rename — the implementation will verify and pick a mounting approach accordingly).
- `IN_CONTAINER_WORKDIR=/asdd_home` is held constant in this feature. The Claude Code per-project path slug derived from this workdir is therefore identical across all project containers; isolation is achieved by giving each container its own copy of the state tree, not by changing the workdir.
- The single-operator, single-host model from prior specs holds: there is one set of credentials per host, owned by one operator, and per-project state does not need user-scoped subdirectories underneath the per-project tree.
- The spec 009 invariants — credential store never leaves `$ASDD_HOME`; subscription auth is the default for all modes — continue to hold. This spec extends spec 009 rather than replacing it.
- The spec 010 invariant — no inbound network port on the container — is unaffected by this change.
- "Removing a project through asdd's existing project-lifecycle command" refers to whatever the current canonical "remove project" operation is at implementation time; this spec does not define a new operator command for cleanup.
