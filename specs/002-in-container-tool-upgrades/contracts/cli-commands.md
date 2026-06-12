# Contract: asdd CLI commands (new in spec 002)

**Feature**: 002-in-container-tool-upgrades
**Status**: New commands. No existing CLI shape changes.
**Caller**: Operator on host shell.

All commands below run as the host user, talk to Docker via `docker exec`, and perform their writes as the `asdd` user inside the container (via `docker exec -u asdd ...`). The container MUST already exist for `<project_id>` — refuse with `ProjectContainerError` if not (a future enhancement could auto-create, out of scope here).

## `asdd versions [<project_id>]`

### Purpose

Show the per-project state of every managed tool: installed version, latest upstream, pin status. Single screen.

### Args

| Arg | Required | Notes |
|---|---|---|
| `<project_id>` | When omitted, default to the project the host's `pwd` resolves to via the registry. If neither is determinable, error with `usage: asdd versions <project_id>`. | |

### Output (success)

Plain text, fit to 80 columns. Columns: tool, installed, latest, pin, status.

```text
PROJECT  dev

TOOL     INSTALLED  LATEST    PIN        STATUS
claude   2.1.150    2.1.151              update available
gh       2.95.0     2.95.0               current
uv       0.4.10     0.4.12   0.4.10     pinned

Run `asdd upgrade <tool> dev` to apply an upgrade. `asdd unpin <tool> dev` removes a pin.
```

### Output (offline / registry unreachable)

```text
TOOL     INSTALLED  LATEST    PIN        STATUS
claude   2.1.150    ?                    could not check
gh       2.95.0     ?                    could not check
uv       0.4.10     ?         0.4.10     pinned
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Report rendered (even if some/all "latest" entries are `?`). |
| 1 | Project unknown OR no container exists for this project AND `--strict` was passed (default: a missing container is fine; we report baseline-only state). |
| 2 | Lock contention reading the manifests (rare). |

### Performance

≤ 3 s wall-clock end-to-end with warm registry. Per-tool probe timeout 2 s, parallel.

---

## `asdd upgrade <tool> <project_id> [--reload]`

### Purpose

Upgrade one named tool inside one project to its latest available version.

### Args

| Arg | Required | Notes |
|---|---|---|
| `<tool>` | Yes | Must be a registered tool name (see `tools.py:TOOLS`). |
| `<project_id>` | Yes | Must be a registered project. |
| `--reload` | No | After install, bounce the running Claude in this project so it picks up the new binary immediately (per R4). No-op if no persistent session is running. |

### Behavior

1. Acquire per-(project, tool) lock at `$ASDD_HOME/_state/tools/<project_id>/<tool>/.lock`.
2. Resolve `latest_version` via the tool's driver. If `latest_version == current_version`, exit 0 with `already current`.
3. Check pin: if pinned and the pin version != latest, refuse with exit 3 unless `--force` (future flag — for now, exit 3 instructs operator to `asdd unpin` first).
4. Run the driver's `install(root, version=latest_version)` — stages to `incoming/`, atomic-renames to `versions/`.
5. Atomically retarget `bin/<tool>` symlink to the new version.
6. Update manifest (`current_version`, `history`, prepend; truncate to 2 entries; remove evicted version dir).
7. If `--reload` AND persistent session for this project: `tmux kill-window` → supervisor restart → `claude --continue`.
8. Print success: `upgraded <tool> in <project>: <from> → <to>`. If no `--reload`, append `(running claude still on <from>; restart with /clear or session restart to load <to>)` when a persistent session is running.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Upgrade succeeded (or already current). |
| 1 | Unknown tool or unknown project. |
| 2 | Lock contention; concurrent upgrade in progress. |
| 3 | Pin in effect; refused. Operator must `asdd unpin` first. |
| 4 | Install failed (network / registry / driver error). Prior version still active. |
| 5 | `--reload` requested but tmux/supervisor restart failed. Install still applied. |

### Idempotency

- Re-running the same `asdd upgrade claude dev` when already at latest is a no-op (exit 0).
- A failed upgrade leaves no manifest changes; re-running attempts the install again from scratch.

---

## `asdd rollback <tool> <project_id>`

### Purpose

Revert to the previous version of `<tool>` for `<project>`. Limited to one step back per the retention cap (FR-011).

### Args

| Arg | Required | Notes |
|---|---|---|
| `<tool>` | Yes | |
| `<project_id>` | Yes | |

### Behavior

1. Acquire lock.
2. Read manifest; if `history.length < 2`, exit 6 with `no prior version to roll back to`.
3. Retarget `bin/<tool>` symlink to `history[1].version`.
4. Update manifest: swap `history[0]` and `history[1]` so the rolled-back-to version is now `history[0]` AND `current_version`. (This lets a subsequent `asdd rollback` undo the rollback — the operation is symmetric.)
5. Print `rolled back <tool> in <project>: <was> → <now>`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Rollback succeeded. |
| 6 | Only one version in history; nothing to roll back to. |
| Others | Same as `upgrade`. |

---

## `asdd pin <tool>=<version> <project_id>` and `asdd unpin <tool> <project_id>`

### Purpose

Lock a tool at its currently-installed version, or remove an existing pin.

### `pin` args

| Arg | Required | Notes |
|---|---|---|
| `<tool>=<version>` | Yes | `<version>` MUST equal the current_version in the manifest. (You can only pin what's installed; upgrade first if needed.) |
| `<project_id>` | Yes | |

### `pin` behavior

1. Acquire lock.
2. Read manifest. Verify `current_version == <version>`. If not, exit 7 with `cannot pin to <version>; current is <current_version> — upgrade first or amend the pin target`.
3. Set `pin = { version, set_at: now }`.

### `unpin` args

| Arg | Required | Notes |
|---|---|---|
| `<tool>` | Yes | |
| `<project_id>` | Yes | |

### `unpin` behavior

1. Acquire lock.
2. Read manifest. If pin is null, exit 0 (idempotent: unpinning what isn't pinned succeeds silently).
3. Set `pin = null`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Pin or unpin recorded. |
| 7 | (pin only) Asked to pin to a version other than current. |
| Others | Same as `upgrade`. |

---

## `asdd reset-tools <tool|--all> <project_id>`

### Purpose

Clear the project's overlay for one tool or all tools. The baseline takes over after the next container restart.

### Args

| Arg | Required | Notes |
|---|---|---|
| `<tool>` or `--all` | Yes | Name a single tool, or pass `--all` to clear every tool in the project's overlay. |
| `<project_id>` | Yes | |

### Behavior

1. Acquire lock(s).
2. Delete the per-tool subdirectory (or every subdirectory under `<project_id>/`) on the host.
3. Remove the corresponding entries from the aggregate `bin/` directory.
4. Print `reset <tool> in <project>: overlay cleared; baseline <baseline_version> takes over on next session`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Reset succeeded. |
| 8 | No overlay state to clear (idempotent succeed with a noop note). |
| Others | Same as `upgrade`. |

---

## Common behaviors

### Container-not-running

For commands that modify in-container state (upgrade/rollback/reset), a running container is *not* required — the host-side overlay can be modified at any time, and the container will pick it up on next start. The commands print a note when no container is running: `container is not running; changes will apply on next start`.

### `--json` flag (all commands)

All commands accept `--json`. Output becomes one structured JSON object per command for scripting:

```json
{ "command": "upgrade", "tool": "claude", "project_id": "dev", "from": "2.1.150", "to": "2.1.151", "reload": false }
```

### Stdout vs. stderr

- Human-readable progress + status → stderr.
- Final result line + `--json` payload → stdout.
- Errors → stderr; exit code is the source of truth.

### Log file

Every upgrade/rollback writes a log entry to `$ASDD_HOME/_state/tools/<project_id>/<tool>/upgrade.log` (append-only). Records: timestamp, action, from, to, exit code, duration_ms. Useful for post-hoc forensics.

### Security

- No command requires root on the host.
- In-container operations run as `asdd` (uid 1000) via `docker exec -u asdd`. No `--privileged`, no `--user root`.
- All upstream HTTP fetches are GET-only and validate TLS via the system cert store.
