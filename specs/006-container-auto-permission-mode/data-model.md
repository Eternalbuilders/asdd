# Data Model: Container Auto Permission Mode for Git

This feature introduces configuration artifacts, not runtime data entities.
The two artifacts and their relationships:

## Entity: Per-project permission guardrail file

- **Location**: `<workspace>/.claude/settings.json` (in-container:
  `/asdd_home/.claude/settings.json`). Canonical source:
  `project_skeleton/.claude/settings.json`.
- **Format**: Claude Code settings JSON.
- **Fields used**:
  - `permissions.deny` — array of `Bash(...)` rule strings blocking destructive
    git operations. Exact set in `contracts/permission-settings.md`.
- **Lifecycle**:
  - *Created* by `asdd/workspace.py:scaffold` at `asdd new` time, into the
    `.claude/` directory that `specify init` has already created.
  - *Committed* to the project repo (shared, not `.local`) so it travels with
    clones and is visible to Claude as project settings.
  - *Read* by the Claude Code process inside that project's container only
    (per-project isolation, spec 003 unaffected).
  - *Backfilled* into pre-existing workspaces by a documented operator copy step.
- **Validation rules**:
  - Must be valid JSON parseable by Claude Code.
  - `permissions.deny` must contain the full rule set from the contract (unit
    test asserts presence).
  - Must not set `permissions.defaultMode` (ignored in project settings; mode is
    set via launch flag — see other entity).
- **Relationships**: independent of the launch configuration; the two together
  produce "git auto-approved, destructive git blocked." Honours constitution VI.

## Entity: Container launch permission mode

- **Not a file** — a launch-time argument applied per container start.
- **Representation**: the literal flag `--permission-mode auto` on each `claude`
  invocation across the three entrypoints (four call sites). Enumerated in
  `contracts/container-launch.md`.
- **Lifecycle**:
  - *Applied* every time a container starts Claude: `asdd serve` (resume +
    fresh), `asdd dispatch` (`claude --print`), `asdd claude`
    (`docker exec ... claude`).
  - *Not applied* to the login flow (`_login_in_container`).
- **Validation rules**:
  - Every Claude-starting path carries the flag (consistency, FR-002); unit test
    asserts presence in the scripts and `attach_claude`.
  - The persistent-session resume path and fresh-start path must both carry it.
- **Relationships**: enabling auto mode is what removes per-command prompts; the
  guardrail file constrains what auto mode is allowed to run.

## Non-entities (explicitly unchanged)

- Credential store, `claude.json`, per-project `~/.claude/` state mounts — spec
  009/003 layout unchanged.
- Container network posture (no inbound port) — spec 010 unchanged.
- Registry, queue dirs, results — untouched.
