# Contract — `asdd logout` teardown order

## Scope

`cmd_logout` (in `asdd/bootstrap.py`) gains a pre-step: stop every running serve before clearing the credential store. Spec 004 clarification Q2 / FR-006 + the logout-while-running edge case.

## Behavioural contract

Order of operations when `asdd logout` is invoked:

1. Enumerate projects with running persistent (serve) containers (use `project_container.is_persistent_running` per registry row).
2. For each such project, in any order:
   - Run the equivalent of `asdd stop <project_id>`: uninstall the launchd babysitter (`supervisor.uninstall`), stop the container (`project_container.stop_container`), remove the container (`project_container.remove_container`).
   - If any step raises, log the error and record the project as a teardown failure; continue with the next project.
3. If any teardown failure was recorded, refuse to clear the credential store. Print a one-line summary listing the failed projects and exit non-zero. The operator resolves the stuck containers (e.g. `docker stop --time=30 <name>`) and re-runs `asdd logout`.
4. If all teardowns succeeded, call `auth.clear(asdd_home)` — which now removes the shared credential surface and every project's per-project state subtree (spec 003 FR-006). Return success.

## Why refuse-on-teardown-failure

A serve container that survives logout holds a valid `bridgeSessionId` against a now-cleared credential store. The next operator account that logs in inherits the orphaned session on their mobile app — a confusing-at-best, security-sensitive-at-worst outcome. Refusing to log out is the conservative default; the operator must explicitly resolve the orphan.

## CLI surface

No new flags. Operators who want force-logout behaviour can manually `docker rm -f` the offending containers first, then re-run `asdd logout`. We do NOT add `--force` in this feature.

## Operator-visible error message

On teardown failure:

```text
asdd: refusing to log out — some serve sessions could not be stopped:
  - hello-world (docker stop failed: exit 137)
  - demo-2 (launchd uninstall failed)
Resolve these (e.g. `docker stop --time=30 asdd-project-hello-world`) and retry `asdd logout`.
```

Exit code: non-zero (consistent with other refuse-to-act paths in bootstrap).

## Unit test contract

| Test | Expected |
|---|---|
| `cmd_logout` with no running serves clears the store and returns success | ✓ |
| `cmd_logout` with one running serve calls `supervisor.uninstall` + `stop_container` + `remove_container` for that project, then `auth.clear` | ✓ |
| `cmd_logout` with two running serves stops both, then clears | ✓ (mock-driven; assert call order: every stop precedes auth.clear) |
| `cmd_logout` with a serve that fails to stop refuses to clear (auth.clear NOT called) and exits non-zero | ✓ |
| Failed-teardown error message names the failing project(s) | ✓ |
