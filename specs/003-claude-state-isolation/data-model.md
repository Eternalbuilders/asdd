# Data Model — 003-claude-state-isolation

This feature changes the on-disk layout under `$ASDD_HOME/_state/claude-auth/`. No databases, no IPC, no schema files — just filesystem.

## On-disk layout (after this feature)

```text
$ASDD_HOME/
└── _state/
    ├── claude-auth/                            # owned by asdd, 0700
    │   ├── claude.json                         # SHARED — account config, mounted at ~/.claude.json in every container (0600)
    │   ├── claude/                             # SHARED CREDENTIALS — only the credential file lives here (0700)
    │   │   └── .credentials.json               # SHARED — OAuth tokens, file-bind-mounted into every container (0600)
    │   ├── per-project/                        # owned by asdd, 0700
    │   │   ├── <project_id_a>/                 # PER-PROJECT — dir-bind-mounted at ~/.claude/ in project A's container (0700)
    │   │   │   ├── projects/                   # Claude Code's per-project state slug (-asdd-home)
    │   │   │   ├── todos/
    │   │   │   ├── shell-snapshots/
    │   │   │   ├── statsig/
    │   │   │   └── ide/
    │   │   └── <project_id_b>/                 # PER-PROJECT — same shape, isolated from <a>
    │   ├── asdd-auth-meta.json                 # SHARED — login source + timestamp (0600)
    │   └── .migration-notice-shown             # SHARED — marker; presence means the upgrade notice was emitted
    └── claude-auth.lock                        # SHARED — advisory flock for structural mutations of the store
```

The legacy layout — `_state/claude-auth/claude/projects/`, `_state/claude-auth/claude/todos/`, etc. — is detected (see R3) and surfaced via a one-time notice. It is not migrated and not deleted; an operator who wants a clean slate runs `asdd logout` followed by `asdd login`.

## Entities

### Shared credential surface

The host-side files that hold OAuth credentials and account configuration. Identical content visible in every project's container.

| Path on host | Mount in container | Mode | Owner | Notes |
|---|---|---|---|---|
| `_state/claude-auth/claude.json` | `~/.claude.json` (file bind, rw) | `0600` | asdd | Account config; `hasTrustDialogAccepted` workspace records |
| `_state/claude-auth/claude/.credentials.json` | `~/.claude/.credentials.json` (file bind, rw) | `0600` | asdd | OAuth tokens; refreshed in-place by Claude (R1) |

Invariants:

- Both files exist on the host before any container starts (materialised by `ensure_mountable`).
- The credential file is overlaid _after_ the per-project dir mount in `docker run` argv (R2).
- `asdd logout` removes the entire `_state/claude-auth/claude/` directory and `claude.json`, forcing a fresh login on next session.
- Concurrent token refreshes from two containers race the same way two host-side Claude processes would; pre-existing condition, unchanged.

### Per-project state directory

One asdd-owned directory per project, holding everything Claude Code writes under `~/.claude/` that isn't credentials.

| Property | Value |
|---|---|
| Host path | `_state/claude-auth/per-project/<project_id>/` |
| Container mount | `~/.claude/` (dir bind, rw) |
| Mode | `0700` |
| Owner | asdd (uid 1000) |
| Lifetime | Bound to the project's lifecycle |
| Pre-created | Yes — `ensure_mountable(asdd_home, project_id)` materialises it before container start (FR-011) |

Subdirectories created at runtime by Claude Code itself (not pre-materialised by asdd):

- `projects/-asdd-home/` — conversation transcripts (`*.jsonl`) + auto-memory (`memory/MEMORY.md`)
- `todos/` — Claude's task list state
- `shell-snapshots/` — captured shell environments
- `statsig/` — telemetry/feature-flag state
- `ide/` — IDE integration state

Invariants:

- Removed when the project is removed (FR-005, project-lifecycle contract).
- Removed by `asdd logout` (FR-006), alongside the shared credential surface.
- Never copied into a project workspace clone or archive — already covered by `.gitignore` rules and archive-exclusion in spec 008.
- The project_id is the same identifier used everywhere else (container name `asdd-project-<project_id>`, tools overlay `_state/tools/<project_id>/`, workspace dir `projects/<project_id>/`).

## State transitions

```text
                    asdd login (first-time, no host login)
                         │
                         ▼
              ┌──────────────────────┐
              │ store exists,        │  ←──┐
              │ claude.json + .creds │     │ asdd login --seed
              │ present              │     │ (re-seed from host)
              └─────────┬────────────┘     │
                        │                  │
                        │ first project    │
                        ▼ start            │
              ┌──────────────────────┐     │
              │ per-project/<id>/    │     │
              │ materialised         │     │
              └─────────┬────────────┘     │
                        │                  │
                        │ project work     │
                        ▼                  │
              ┌──────────────────────┐     │
              │ transcripts, memory, │     │
              │ todos accumulating   │     │
              └─────────┬────────────┘     │
                        │                  │
            ┌───────────┴─────────────┐    │
            │                         │    │
            │ project remove          │    │ asdd logout
            ▼                         ▼    │
  ┌──────────────────┐    ┌──────────────────────┐
  │ per-project/<id>/│    │ entire claude-auth/  │
  │ removed          │    │ removed (incl.       │
  │                  │    │ all per-project/)    │
  └──────────────────┘    └──────────────────────┘
```

## Boundaries

- **In scope**: layout under `_state/claude-auth/`; `auth_mounts` API; `ensure_mountable` behaviour; `auth.clear` behaviour; project-lifecycle removal step; first-run migration notice.
- **Out of scope**: changing `IN_CONTAINER_WORKDIR`; changing what Claude Code writes into `~/.claude/`; cross-host credential sharing; multi-user-on-one-host scenarios.
