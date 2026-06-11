# Contract: `asdd claude <project>` (new)

**Feature**: 001-container-shell-and-gh
**Status**: New command.

## Purpose

Start an interactive Claude Code session inside the project's container with the same auth, mounts, and environment that `asdd open` previously provided. When Claude exits, the operator returns to the host and the container stops.

## Invocation

```bash
asdd claude <project_id>
```

| Argument | Type | Required | Notes |
|---|---|---|---|
| `project_id` | str (positional) | yes | Must exist in the asdd registry. |

No options. No env-var inputs.

## Behavior

1. Look up `project_id` in the registry. If absent → exit 1 with `BootstrapError`.
2. If `is_persistent_running(project_id)` returns true → return `attach_session(project_id)` (tmux attach to the running Claude). The persistent session's `--restart unless-stopped` semantics are preserved; this command's exit does NOT stop the session.
3. Call `_require_login(asdd_home, interactive=True)`. On missing auth → exit 1 with `BootstrapError` (same message `asdd open` produces today).
4. Call `ensure_image_built()`.
5. Call `assert_not_running(project_id)`. On already-running interactive/dispatch container → exit 1 with `AlreadyRunningError`.
6. Decrypt project secrets via `_decrypt_project_secrets`.
7. Build a `ProjectContainer(mode="interactive", …)` and call `start_container(pc, extra_env=project_secrets)` — same as `asdd open`. `ASDD_PROJECT_ID` is plumbed in.
8. Call `attach_claude(project_id)` — runs `docker exec -it <name> claude`. Return its exit code via `try/finally` that calls `stop_container(project_id)`.

## Returns

- Exit code: Claude's exit code.
- Persistent-session branch returns tmux's exit code (matching today's `attach_session` semantics).

## What this contract guarantees

- The operator lands at a Claude prompt, never at a bash shell.
- The container stops on Claude exit (interactive branch).
- The persistent session is preserved if one was running.
- `ASDD_PROJECT_ID` is set in the container's environment so any sub-shell Claude spawns shows the project name.
- Auth is gated identically to `asdd open` (`_require_login` is shared).

## What this contract explicitly does NOT do

- Does NOT start a bash shell.
- Does NOT start a second Claude alongside a persistent session.
- Does NOT alter the persistent session's lifecycle (it continues running after the operator detaches).

## New symbols

In `asdd/bootstrap.py`:

| Symbol | Purpose |
|---|---|
| `cmd_claude(*, asdd_home: Path, project_id: str) -> int` | Implements steps 1–8 above. Returns the inner exit code. |
| `_cli_claude(project_id: str)` | Click command wrapping `cmd_claude`. Translates `BootstrapError`/`AlreadyRunningError`/`ProjectContainerError` to `click.echo(... err=True) + sys.exit(1)`. |

In `asdd/project_container.py`:

| Symbol | Purpose |
|---|---|
| `attach_claude(project_id: str) -> int` | `subprocess.run(["docker", "exec", "-it", container_name(project_id), "claude"], check=False).returncode`. |

`attach_claude` is exported through the module `__all__` alongside `attach_shell`.

## Tests

- **Unit: `tests/unit/test_bootstrap_cli.py`** — Click runner against `asdd claude`. Cases:
  - happy path: monkeypatched `cmd_claude` returns 0; CLI exits 0.
  - missing project: `BootstrapError` → CLI exits 1, message on stderr.
  - already running: `AlreadyRunningError` → CLI exits 1.
- **Unit: `tests/unit/test_persistent_session.py`** — new `test_claude_attaches_when_persistent` mirroring the existing open-attaches-when-persistent test, but exercising `cmd_claude` and asserting `attach_session` is called.
- **Unit: `tests/unit/test_project_container.py`** — assert `attach_claude` invokes `docker exec -it <name> claude` (subprocess args verified via `monkeypatch.setattr(subprocess, "run", spy)`).
- **Integration: `tests/integration/test_image_smoke.py`** — sanity-only assertion that `claude` is on `$PATH` inside the image (existing assertion, no change required). Note: a real Claude launch is out of scope for image smoke.

## Examples

```bash
# Start a new Claude session inside the my-app container.
asdd claude my-app

# Re-attach to a persistent session if one is running.
# (The same command "just works" in both cases.)
asdd claude my-app
```
