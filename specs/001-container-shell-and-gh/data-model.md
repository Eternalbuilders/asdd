# Data Model: Container shell vs. Claude entry points

**Feature**: 001-container-shell-and-gh
**Date**: 2026-06-11

This feature does not introduce persistent state. The entities below are the surfaces and contracts the implementation touches.

## CLI command — `asdd open` (revised)

| Attribute | Value |
|---|---|
| Click command name | `open` |
| Argument | `project_id: str` |
| Help text | "Open a project's container at an interactive bash shell (no Claude)." |
| Returns | `int` — bash exit code from inside the container |
| Pre-conditions | Project is registered in the asdd registry; container is not running in any mode. |
| Post-conditions | Container is stopped on exit. |
| Side effects | Mounts auth store + workspace per existing `start_container`; passes `ASDD_PROJECT_ID=<project_id>` via `extra_env`. |
| Errors | `BootstrapError`, `AlreadyRunningError`, `ProjectContainerError`. New: refuses with `AlreadyRunningError` when a persistent session is running (was: silent re-attach). |

## CLI command — `asdd claude` (new)

| Attribute | Value |
|---|---|
| Click command name | `claude` |
| Argument | `project_id: str` |
| Help text | "Start an interactive Claude Code session in a project's container." |
| Returns | `int` — Claude's exit code |
| Pre-conditions | Project is registered; container is not running EXCEPT when a persistent session is running (then re-attach). |
| Post-conditions | Container is stopped on exit (or the persistent session continues if re-attached). |
| Side effects | Same mounts as `asdd open` plus the existing subscription-auth mounts; passes `ASDD_PROJECT_ID` via `extra_env`. |
| Errors | `BootstrapError` (auth missing), `AlreadyRunningError` (non-persistent container already running), `ProjectContainerError`. |

State transitions:

| Event | Pre-state | Action | Post-state |
|---|---|---|---|
| `asdd claude <p>` (no container) | container not running | start interactive container, `attach_claude`, stop on exit | container stopped |
| `asdd claude <p>` (persistent session) | session running | `attach_session` (tmux attach) | session keeps running after detach |
| `asdd claude <p>` (interactive container running) | interactive running | raise `AlreadyRunningError` | no change |
| `asdd claude <p>` (auth missing) | no auth store | raise `BootstrapError` from `_require_login` | no change |

## Helper — `attach_claude(project_id: str) -> int`

A new top-level function in `asdd/project_container.py`, parallel to `attach_shell`.

```text
Signature : attach_claude(project_id: str) -> int
Side effect: subprocess.run(["docker", "exec", "-it", container_name(project_id), "claude"], check=False)
Returns   : the subprocess returncode (== claude's exit code)
```

Symmetric to `attach_shell`. No I/O capture (interactive TTY only).

## Env var — `ASDD_PROJECT_ID`

| Attribute | Value |
|---|---|
| Scope | Container-level env, set at create time by `start_container`. |
| Value | The project identifier (same string used for `container_name`, `registry` row, etc.). |
| Read by | `/etc/profile.d/asdd-prompt.sh` inside the container. |
| Lifetime | The lifetime of the container. |
| Persistence | None — runtime-only. |

## In-container artifact — `/etc/profile.d/asdd-prompt.sh`

| Attribute | Value |
|---|---|
| Path in image | `/etc/profile.d/asdd-prompt.sh` |
| Source path in repo | `docker/files/asdd-prompt.sh` |
| Mode | `0644` (Debian default for profile.d entries) |
| Behavior | If `$- == *i*` (interactive) AND `ASDD_PROJECT_ID` is non-empty, set `PS1="(${ASDD_PROJECT_ID}) ${PS1}"`. |
| Idempotency | Re-sourcing in a sub-shell is harmless — PS1 has already absorbed the prefix once and the env var is unchanged; the script is a no-op if the prefix is already present (checked via a guard). |

## Image-level contract — `asdd/project:latest`

| Contract | Today | After this feature |
|---|---|---|
| `gh` present on `$PATH` | yes (`2.92.0`) | yes (`2.94.0`) |
| `gh` works on amd64 and arm64 | yes | yes (no change) |
| Default `PS1` | Debian default (`\u@\h:\w\$ `) | Debian default with `(<project>) ` prefix when `ASDD_PROJECT_ID` is set |
| `/etc/profile.d/asdd-prompt.sh` | absent | present, `0644` |
| Default CMD | `bash` | `bash` (unchanged) |
| Other tooling (`git`, `gh`, `sops`, `uv`, `claude`, `tmux`) | present | present (no change) |

## Registry interaction

None. The asdd registry is read-only on this path (`_registry_lookup`). No registry schema changes.

## Migration / compatibility notes

- Existing images keep working but lack the prompt prefix until rebuilt. Once rebuilt, the prefix appears.
- Existing `asdd open` callers that expected to land in Claude will now land in bash. Per spec FR-013, the docs explain the change.
- No data migration is required.
