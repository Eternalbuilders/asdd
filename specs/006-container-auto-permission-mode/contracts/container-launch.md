# Contract: Container launch in `auto` permission mode

Every path that starts the `claude` CLI inside a project container MUST pass
`--permission-mode auto`. The login flow is the sole exception.

## Required call sites

| # | Mode | File / symbol | Current call | After |
|---|------|---------------|--------------|-------|
| 1 | `asdd serve` resume | `docker/files/asdd-session.sh:45` | `claude --continue --remote-control --name "$NAME"` | `claude --permission-mode auto --continue --remote-control --name "$NAME"` |
| 2 | `asdd serve` fresh | `docker/files/asdd-session.sh:48` | `claude --remote-control --name "$NAME"` | `claude --permission-mode auto --remote-control --name "$NAME"` |
| 3 | `asdd dispatch` | `docker/files/asdd-run-job.sh:41` | `claude --print < "$JOB_PATH"` | `claude --permission-mode auto --print < "$JOB_PATH"` |
| 4 | `asdd claude` | `asdd/project_container.py:attach_claude` (≈L448) | `["docker","exec","-it",<c>,"claude"]` | `[...,"claude","--permission-mode","auto"]` |

## Exclusions

- `asdd/project_container.py:_login_in_container` (≈L688) — the `claude` login
  invocation MUST NOT receive the flag; login is not a working session.
- `asdd open` — starts bash, not claude; no change. (If an operator manually
  runs `claude` from an `asdd open` shell, the deny-guards still apply, but auto
  mode is their choice; out of scope.)

## Guarantees

- **G1 (consistency)**: All four working-session call sites carry the flag, so
  every container exhibits identical approval behaviour (FR-002).
- **G2 (resume parity)**: Both the `--continue` and fresh-start branches in
  `asdd-session.sh` carry it, so a resumed persistent session does not silently
  fall back to prompting.
- **G3 (process model intact)**: The flag decorates the existing single `claude`
  launch; no extra process is spawned (preserves the one-Claude-per-container
  invariant).
- **G4 (unattended start)**: Combined with `auth.ensure_workspace_trusted`
  pre-accepting the permission-rules prompt, `serve`/`dispatch` start without any
  interactive approval (FR-009).

## Verification hooks

- Unit (`tests/unit/test_session_script.py` style): grep the shipped
  `asdd-session.sh` / `asdd-run-job.sh` for `--permission-mode auto` on the
  claude lines; assert `attach_claude` builds the flag and `_login_in_container`
  does not.
- Integration (docker-gated): start a session container and confirm a routine
  git command runs unprompted while a denied one is blocked.
