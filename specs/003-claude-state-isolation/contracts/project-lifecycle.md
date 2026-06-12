# Contract — Project-lifecycle: per-project state cleanup

## Scope

The existing canonical "remove project" operation (`asdd/lifecycle.py`) is extended to remove the project's per-project Claude state directory alongside the container, the tools overlay, and the workspace.

This contract does not introduce a new operator command. It modifies the behaviour of whatever code path implements project removal today.

## Behavioural contract

Given a project with `project_id = "p"`:

1. **Pre-removal state** — host-side directories exist:
   - `$ASDD_HOME/projects/p/` (workspace)
   - `$ASDD_HOME/_state/tools/p/` (tools overlay, from spec 002)
   - `$ASDD_HOME/_state/claude-auth/per-project/p/` (NEW — per-project Claude state)
   - Docker container `asdd-project-p` (if started)

2. **Removal step order** (preserving the existing ordering for the prior three; the new step is additive):
   1. Stop container if running
   2. Remove container
   3. Remove `_state/tools/p/`
   4. **NEW**: Remove `_state/claude-auth/per-project/p/` (idempotent; absent is fine)
   5. Remove `projects/p/` workspace

3. **Post-removal state**:
   - All four host directories absent
   - No other project's per-project state directory touched
   - Shared credential surface (`_state/claude-auth/claude.json`, `_state/claude-auth/claude/.credentials.json`) untouched

## Failure semantics

- If the per-project state directory removal fails (permission error, busy file), the existing failure-handling pattern in `lifecycle.py` is reused: log the error, continue with subsequent removal steps, exit nonzero with a summary. The operator should not be blocked from completing removal of the workspace by a per-project state file holdout.
- If the per-project state directory is missing at the time of removal (e.g., the project never started a container, or a previous partial removal already cleaned it), removal is a no-op. Idempotent.

## `asdd logout` contract

`auth.clear(asdd_home)` (called from the `asdd logout` command) is extended to remove the entire `_state/claude-auth/` tree — both the shared credential surface AND every `per-project/<id>/` directory in a single operation.

Pre-existing contract: idempotent; returns `True` iff something was removed.

New behaviour: a successful clear removes per-project state for every project. This matches FR-006 ("logout MUST remove both the shared credential surface AND all per-project state trees — it's all one logical credential surface").

## Unit test contract

| Test | Expected |
|---|---|
| `lifecycle.remove_project("p")` against a project with `per-project/p/` removes it | ✓ |
| `lifecycle.remove_project("p")` against a project without `per-project/p/` succeeds (idempotent) | ✓ |
| `lifecycle.remove_project("p")` does not touch `per-project/q/` | ✓ |
| `auth.clear(home)` removes `per-project/` along with `claude/` and `claude.json` | ✓ |
| `auth.clear(home)` on a home without `per-project/` succeeds (idempotent) | ✓ |
