# Contract — `auth_mounts(asdd_home, project_id)`

## Signature

```python
def auth_mounts(
    asdd_home: Path,
    project_id: str | None = None,
) -> list[tuple[str, str, str]]:
    ...
```

Returns Docker bind-mount tuples `(host_path, container_path, mode)` for the credential store, in the order they must be passed to `docker run`.

## Inputs

- `asdd_home` — the asdd state root. Used to derive every host path. Must exist.
- `project_id` — the container's project identifier when one exists, or `None` for the throwaway interactive-login container.

## Outputs

### Case A — `project_id is None` (throwaway login)

Returns exactly **two** tuples, in this order:

```python
[
    (str(store_json_path(asdd_home)),     "/home/asdd/.claude.json",                "rw"),
    (str(credentials_file(asdd_home)),    "/home/asdd/.claude/.credentials.json",   "rw"),
]
```

The directory mount is omitted. The throwaway container is `--rm`, so any per-project state it writes inside `~/.claude/` is ephemeral by definition.

### Case B — `project_id is "<id>"` (project container)

Returns exactly **three** tuples, in this order:

```python
[
    (str(store_json_path(asdd_home)),                 "/home/asdd/.claude.json",              "rw"),
    (str(per_project_dir(asdd_home, project_id)),     "/home/asdd/.claude",                   "rw"),
    (str(credentials_file(asdd_home)),                "/home/asdd/.claude/.credentials.json", "rw"),
]
```

Order is contractual. The directory mount at `~/.claude` MUST precede the file mount inside it (R2). `start_container` and friends MUST preserve list order when building argv.

## Side effects

`auth_mounts` calls `auth.ensure_mountable(asdd_home, project_id)` before returning. `ensure_mountable` materialises:

- `_state/claude-auth/claude.json` as a placeholder file (mode `0600`) if absent
- `_state/claude-auth/claude/.credentials.json` as a placeholder file (mode `0600`) if absent
- `_state/claude-auth/per-project/<project_id>/` as a directory (mode `0700`) if `project_id` is supplied and absent

Idempotent. Self-healing: if a previous container start auto-created any of these as the wrong type (Docker creates missing bind targets as directories), `ensure_mountable` removes the bad placeholder and re-creates it correctly.

## Caller obligations

- `interactive_mounts`, `autonomous_mounts`, `_compose_mounts` (in `project_container.py`) MUST forward their `project_id` to `auth_mounts`. The login-flow caller (`interactive_login_run`) MUST pass `None`.
- All current callers of the no-argument `auth_mounts(asdd_home)` MUST be updated to either pass a `project_id` or `None`.

## Unit test contract

| Test | Expected |
|---|---|
| `auth_mounts(home, None)` returns 2 tuples | ✓ |
| `auth_mounts(home, "p")` returns 3 tuples | ✓ |
| In Case B, container paths are `[…claude.json, …claude, …claude/.credentials.json]` in that order | ✓ |
| All returned modes are `"rw"` | ✓ |
| Calling `auth_mounts(home, "p")` against a fresh home creates `per-project/p/` with mode `0700` | ✓ |
| Calling `auth_mounts(home, "p")` against a home where `claude/.credentials.json` exists as a directory (Docker damage) heals the file | ✓ |
| Calling `auth_mounts(home, "p")` against a home where `.credentials.json` already has real content does NOT clobber it | ✓ |
