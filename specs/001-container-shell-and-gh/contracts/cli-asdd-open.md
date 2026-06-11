# Contract: `asdd open <project>` (revised)

**Feature**: 001-container-shell-and-gh
**Status**: Revised. Public Click command, signature unchanged; behavior change to "shell only, never Claude" is codified here.

## Purpose

Drop the operator into an interactive bash shell inside the project's container. Never start Claude.

## Invocation

```bash
asdd open <project_id>
```

| Argument | Type | Required | Notes |
|---|---|---|---|
| `project_id` | str (positional) | yes | Must exist in the asdd registry. |

No options. No env-var inputs.

## Behavior

1. Look up `project_id` in the registry. If absent → exit 1 with `BootstrapError` message.
2. If `is_persistent_running(project_id)` returns true → exit 1 with a clear message ("A persistent session is running for this project. Use `asdd attach` to join it or `asdd claude` to start a new Claude inside it."). **This is the behavior change**: previously this branch returned `attach_session(...)`, which landed the operator in Claude.
3. Call `_require_login(asdd_home, interactive=True)`. On missing auth → exit 1 with `BootstrapError`.
4. Call `ensure_image_built()`.
5. Call `assert_not_running(project_id)`. On already-running interactive/dispatch container → exit 1 with `AlreadyRunningError`.
6. Decrypt project secrets via `_decrypt_project_secrets`.
7. Build a `ProjectContainer(mode="interactive", …)` and call `start_container(pc, extra_env=project_secrets)`. The implementation MUST pass `ASDD_PROJECT_ID=<project_id>` in `extra_env` so the in-container prompt picks it up.
8. Call `attach_shell(project_id)` — runs `docker exec -it <name> bash`. Return its exit code via `try/finally` that calls `stop_container(project_id)`.

## Returns

- Exit code: bash's exit code from inside the container.
- `0` on a clean `exit`; non-zero on an interrupted or failed bash session. The container is stopped on the `finally` regardless.

## What this contract guarantees

- The operator lands at a bash prompt, never at Claude.
- The container is stopped on shell exit.
- If anything else is already running for the project, the command refuses rather than masking the conflict.
- `ASDD_PROJECT_ID` is set in the container's environment so the prompt customization fires.

## What this contract explicitly does NOT do

- Does NOT start Claude.
- Does NOT join an existing persistent session (use `asdd attach`).
- Does NOT run any in-container automation (use `asdd dispatch`).

## Symbol changes in `asdd/bootstrap.py`

| Symbol | Change |
|---|---|
| `_cli_open(project_id)` | help text revised. Body unchanged. |
| `cmd_open(*, asdd_home, project_id)` | docstring revised. Persistent-session branch replaced: instead of returning `attach_session(...)`, raise `AlreadyRunningError(project_id, mode="persistent")` (or equivalent message via `ProjectContainerError`). |

## Symbol changes in `asdd/project_container.py`

| Symbol | Change |
|---|---|
| `start_container(...)` | Caller adds `ASDD_PROJECT_ID` to `extra_env`. No signature change. |

## Backwards compatibility

- For operators with cached images that do not include the prompt prefix, the command still works; only the prompt prefix is absent.
- For operators who previously relied on `asdd open` to join a running persistent session, the error message names the right command (`asdd attach`).

## Tests

- **Unit (existing test file): `tests/unit/test_persistent_session.py`** — replace `test_open_attaches_when_persistent` with a test that asserts `cmd_open` raises (or exits non-zero) when persistent is running, and that `attach_session` is NOT called.
- **Unit: `tests/unit/test_project_container.py`** — assert `start_container` propagates `ASDD_PROJECT_ID` from `extra_env` into the `docker create` command line.
- **Integration: `tests/integration/test_image_smoke.py`** — assert that `docker run --rm -e ASDD_PROJECT_ID=foo asdd/project:latest bash -lic 'echo "$PS1"'` includes `(foo)` in the output.
