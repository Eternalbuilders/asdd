# Feature Specification: Container Auto Permission Mode for Git

**Feature Branch**: `006-container-auto-permission-mode`

**Created**: 2026-06-13

**Status**: Draft

**Input**: User description: "Make all asdd containers let Claude run git commands without per-command approval, consistently, by starting Claude in auto permission mode, while keeping hard guardrails against destructive git operations."

## Clarifications

### Session 2026-06-13

- Q: Should the low-friction auto permission mode apply to the interactive
  `asdd claude` launch as well as the unattended `serve`/`dispatch` modes, or be
  limited to the unattended modes? → A: Apply it in **all** ways Claude is
  started — `asdd serve`, `asdd dispatch`, and interactive `asdd claude` — so
  every launch path starts in auto permission mode.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Git just works in every container (Priority: P1)

When the operator drives Claude inside any asdd container — a persistent
`asdd serve` session, an autonomous `asdd dispatch` job, or an interactive
`asdd claude` session — Claude can run routine git commands (status, diff, add,
commit, branch, push to a feature branch, `gh` operations) without stopping to
ask the operator for per-command approval. The behaviour is identical across
every container; there is no "lucky" container where git flows and another where
every command prompts.

**Why this priority**: This is the core problem. Today behaviour is inconsistent
— some containers run frictionlessly while others halt on every git command —
which blocks autonomous and persistent runs and forces the operator to babysit
approvals. Consistency is the whole point of the feature.

**Independent Test**: Start a container in each mode, ask Claude to run
`git status` and commit + push to a feature branch, and confirm no approval
prompt appears in any mode.

**Acceptance Scenarios**:

1. **Given** a freshly scaffolded project, **When** the operator runs
   `asdd claude <id>` and asks Claude to `git status` and `git commit`, **Then**
   the commands run without a per-command approval prompt.
2. **Given** an `asdd dispatch` job whose markdown instructs a commit and push to
   a feature branch, **When** the job runs unattended, **Then** the git
   commands complete without blocking on approval.
3. **Given** two containers for two different projects, **When** the same git
   command is issued in each, **Then** both behave identically (neither prompts).

---

### User Story 2 - Destructive git stays blocked (Priority: P1)

Even with routine git auto-approved, the operations the project's conventions
forbid — force-push, hard reset, history rewrite via rebase, and commits that
skip hooks — are refused outright in every mode, with no way for Claude to slip
one through unattended.

**Why this priority**: Auto-approval without guardrails is unacceptable — it
would let an unattended or confused session rewrite history or force-push.
Constitution principle VI requires `main` be protected from destructive
operations. This guardrail is co-equal with US1; shipping US1 without it would
regress safety.

**Independent Test**: In any mode, ask Claude to run `git push --force`,
`git reset --hard`, `git rebase`, and `git commit --no-verify`, and confirm each
is blocked rather than executed.

**Acceptance Scenarios**:

1. **Given** any container, **When** Claude attempts `git push --force` (or
   `-f`, or a reordered variant), **Then** the command is blocked.
2. **Given** any container, **When** Claude attempts `git reset --hard`,
   `git rebase`, or `git commit --no-verify`, **Then** each is blocked.
3. **Given** an unattended `asdd dispatch` job, **When** its instructions would
   lead to a destructive git operation, **Then** the operation is blocked
   without any human present to intervene.

---

### User Story 3 - New and existing projects are covered (Priority: P2)

The guardrails apply automatically to every newly created project with no manual
setup, and there is a defined way to apply the same guardrails to projects that
already exist.

**Why this priority**: Without automatic provisioning the feature would rely on
each operator remembering to configure each project — exactly the drift this
feature removes. Existing-project coverage matters but can follow the new-project
path, so it is P2.

**Independent Test**: Scaffold a new project and confirm the guardrails are
present with zero manual steps; then apply the documented/automated backfill to a
pre-existing project and confirm the guardrails are present there too.

**Acceptance Scenarios**:

1. **Given** a brand-new project created by the scaffolder, **When** its
   workspace is inspected, **Then** the guardrail configuration is present
   without any manual action.
2. **Given** a project created before this feature, **When** the operator runs
   the documented backfill step, **Then** the guardrails become active for that
   project.

---

### Edge Cases

- **Reordered / obfuscated destructive commands**: command matching is literal,
  so guardrails must cover common phrasings (`git push --force`, `git push -f`,
  `git push origin main --force`, `git -c ... push --force`). Variants that evade
  literal matching are a known limitation, mitigated by also keeping the written
  convention in the agent instructions.
- **Compound commands**: a chain like `git status && git push --force` must be
  blocked because one of its sub-commands is forbidden.
- **First-run trust prompt**: a workspace that defines its own permission rules
  can trigger a one-time "approve these project permission rules?" prompt; in
  unattended modes this must be pre-accepted so it does not silently stall.
- **Resume vs fresh session**: the persistent session both resumes prior
  conversations and starts fresh ones; both launch paths must apply the mode.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every container mode that runs Claude (persistent `asdd serve`,
  autonomous `asdd dispatch`, and interactive `asdd claude`) MUST start Claude so
  that routine git and `gh` commands execute without per-command operator
  approval.
- **FR-002**: Git-approval behaviour MUST be consistent across all containers —
  there MUST NOT be containers that prompt and others that do not for the same
  command.
- **FR-003**: Destructive git operations — force-push (any phrasing), hard
  reset, rebase, and hook-skipping commits — MUST be blocked outright in every
  mode, and the block MUST take effect even when routine git is auto-approved.
- **FR-004**: The destructive-operation guardrails MUST be applied automatically
  to every newly scaffolded project with no manual operator step.
- **FR-005**: A defined path (documented step and/or tooling) MUST exist to apply
  the same guardrails to projects created before this feature.
- **FR-006**: The solution MUST NOT grant unguarded full permission bypass; an
  approach that disables all permission checks is explicitly rejected.
- **FR-007**: Auto-approval MUST retain an automatic safety review for actions
  that fall outside the requested scope or target unrecognized external
  infrastructure (i.e. auto-approval is not a blanket "yes to everything").
- **FR-008**: This feature MUST NOT change the credential/auth model, the
  per-project state isolation, or the container's no-inbound-port network
  posture.
- **FR-009**: Unattended modes MUST NOT stall on a first-run "approve project
  permission rules" prompt; any such prompt MUST be pre-accepted so guardrails
  apply without a human present.
- **FR-010**: Operator documentation MUST be updated so the previously required
  manual "start the session in automode yourself" step is no longer necessary,
  and the new default and its guardrails are described.

### Key Entities

- **Per-project guardrail configuration**: a checked-in, version-controlled
  artifact in each project's workspace that declares the forbidden destructive
  git operations. Travels with the project and is read inside that project's
  container only.
- **Container launch configuration**: the per-mode setting that puts Claude into
  the low-friction approval mode when a container starts; distinct from the
  per-project guardrail artifact and shared by all modes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In every container mode, routine git commands (status, add,
  commit, push to a feature branch) and `gh` commands complete with zero
  per-command approval prompts.
- **SC-002**: 100% of containers exhibit identical git-approval behaviour; no
  container both exists and disagrees with the others for the same command.
- **SC-003**: Force-push, hard reset, rebase, and hook-skipping commits are
  blocked in 100% of attempts across all modes.
- **SC-004**: A newly scaffolded project has the guardrails active with zero
  manual setup steps.
- **SC-005**: The operator no longer performs any manual per-session step to
  enable autonomous git; the previously documented manual automode step is
  removed.

## Assumptions

- **Interactive scope included** (confirmed in clarification): `asdd claude` is
  in-scope for the auto permission mode alongside `serve`/`dispatch`, so every
  launch path starts in auto mode and all modes behave identically.
- **Branch-agnostic guardrails**: destructive operations are blocked regardless
  of the current branch, which is stricter than — and therefore satisfies —
  constitution VI's protection of `main`. Per-branch nuance is out of scope.
- **Backfill is a documented step by default**: existing projects are covered via
  a documented operator step; promoting it to a dedicated subcommand is a
  possible refinement, not a requirement of this feature.
- **Reliance on the platform's auto-approval safety review**: the low-friction
  mode is expected to provide a built-in safety review (scope/external-infra
  checks); guardrails in this feature are the deterministic floor layered on top
  of it, not a replacement for it.
- **Auth/state model unchanged**: the shared subscription credential store,
  per-project state isolation, and outbound-only networking from prior specs
  (009, 003, 010) remain exactly as they are.

## Dependencies

- Builds on the container modes established by features 001 (shell/claude entry
  points), 008/009 (dispatch + auth), and 010 (persistent serve session).
- Honours constitution principle VI (default branch protection) and IV
  (container-portable runtime; sole shared host resource is `~/.claude/`).
