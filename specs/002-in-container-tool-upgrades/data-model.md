# Data Model: In-Container Tool Upgrades

**Feature**: 002-in-container-tool-upgrades
**Date**: 2026-06-12

## Entity overview

```text
ManagedTool (registry, in-code)        Manifest (on-disk JSON, per project per tool)
─────────────────────────────────       ────────────────────────────────────────────
name              PK                    project_id            (host directory key)
driver_method                           tool_name        FK   ManagedTool.name
source_id                               current_version
binary_name                             history            [VersionRecord, max 2]
                                        pin               (nullable)
                                        last_checked_at   (unix seconds)
                                        schema_version    (integer; starts at 1)

VersionRecord (embedded in Manifest)    Pin (embedded in Manifest)
─────────────────────────────────       ──────────────────────────────
version                                 version
installed_at      (unix seconds)        set_at            (unix seconds)
install_method
size_bytes

UpgradePlan (transient, CLI-side)       VersionCache (single host-wide file)
─────────────────────────────────       ───────────────────────────────────────
project_id                              entries           [CacheEntry]
project_path
tools             [(name, from, to)]    CacheEntry
                                        ─────────────
                                        tool_name        FK   ManagedTool.name
                                        latest_version
                                        checked_at       (unix seconds; entries
                                                          older than 5 min are stale)
```

## ManagedTool (registry; in-code, not persisted)

Declared in `asdd/tools.py` as a module-level dict. Adding a tool = adding one entry plus a driver if the install method is new.

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | The registry key. Matches the binary name the operator types. Example: `"claude"`. |
| `driver_method` | `Literal["npm-global", "github-release", "astral-install"]` | Selects which driver in `asdd/tools.py` handles install/uninstall/version-probe. |
| `source_id` | `str` | Per-driver source identifier. For `npm-global`: the package name (`"@anthropic-ai/claude-code"`). For `github-release`: `"<owner>/<repo>"` (`"cli/cli"`). For `astral-install`: `"astral-sh/uv"`. |
| `binary_name` | `str` | The basename of the binary the symlink should point at inside the overlay. Usually equals `name`. |

Initial registry (launched with):

```python
TOOLS = {
    "claude": ManagedTool(name="claude", driver_method="npm-global",
                          source_id="@anthropic-ai/claude-code", binary_name="claude"),
    "gh":     ManagedTool(name="gh",     driver_method="github-release",
                          source_id="cli/cli", binary_name="gh"),
    "uv":     ManagedTool(name="uv",     driver_method="astral-install",
                          source_id="astral-sh/uv", binary_name="uv"),
}
```

## Manifest (on-disk JSON per project per tool)

Path: `$ASDD_HOME/_state/tools/<project_id>/<tool_name>/manifest.json`. Owned by the `asdd` user. Schema-versioned for forward compatibility.

```json
{
  "schema_version": 1,
  "tool_name": "claude",
  "current_version": "2.1.151",
  "pin": null,
  "history": [
    {
      "version": "2.1.151",
      "installed_at": 1749738203,
      "install_method": "npm-global",
      "size_bytes": 47193847
    },
    {
      "version": "2.1.150",
      "installed_at": 1749651803,
      "install_method": "npm-global",
      "size_bytes": 47180000
    }
  ],
  "last_checked_at": 1749738850
}
```

| Field | SQL-ish type | Notes |
|---|---|---|
| `schema_version` | INTEGER NOT NULL | Starts at 1. Bumps on incompatible changes; readers refuse to load unknown versions. |
| `tool_name` | TEXT NOT NULL | Matches `ManagedTool.name`. Redundant with the directory path; kept for self-contained logs/exports. |
| `current_version` | TEXT NOT NULL | Version the overlay's `bin/<binary>` symlink currently resolves to. Must match one entry in `history`. |
| `pin` | NULLABLE OBJECT | If non-null, contains `version` (TEXT) and `set_at` (INTEGER). When pinned, bulk upgrades skip this tool. |
| `history` | ARRAY OF VersionRecord | Most-recent-first. Capped at 2 by retention (the *current* + one prior; on upgrade, the third-oldest is evicted from disk and history). |
| `last_checked_at` | INTEGER NULLABLE | Unix seconds of the most recent successful upstream version probe. Used to skip redundant rechecks within the 5-minute cache window. |

Validation rules:

- `current_version` MUST equal `history[0].version`.
- `pin.version`, when present, MUST equal `current_version`. (You can only pin to what's installed. Pinning to an uninstalled version is rejected at the CLI.)
- `history.length` MUST be ≤ 2.
- Schema version 1 is the only loadable version; unknown versions are a hard refusal with a clear message.

State transitions (a single tool's lifecycle in a single project):

| Event | Precondition | Mutation |
|---|---|---|
| First install (overlay empty, baseline takes over) | No `manifest.json` for `(project, tool)`. | None. The baseline serves; no manifest is created until the first upgrade. |
| `asdd upgrade <tool>` (first time) | Driver succeeds installing version `V`. | Create `manifest.json` with `current_version=V`, `history=[V_record]`, `pin=null`. Update overlay symlink. |
| `asdd upgrade <tool>` (subsequent) | Driver succeeds installing `V'`. Prior `current_version=V`. | Prepend `V'_record` to `history`. Truncate to last 2 entries (evicting `V_old`). Remove `versions/V_old/` from disk. Update overlay symlink. Set `current_version=V'`. |
| `asdd upgrade <tool>` (Resend failure / install failure) | Driver raises. | No manifest write. Prior `current_version` stays live (symlink untouched). |
| `asdd rollback <tool>` | `history.length` ≥ 2. | Set `current_version` to `history[1].version`. DO NOT modify `history` (so the operator can rollback-forward later). Update overlay symlink. |
| `asdd pin <tool>=<version>` | `version` equals `current_version`. | Set `pin = { version, set_at: now }`. |
| `asdd unpin <tool>` | `pin` is non-null. | Set `pin = null`. |
| `asdd reset-tools <tool>` | Any state. | Delete the per-tool subdirectory entirely; baseline takes over. |
| Banner check after upgrade | Any time. | Read-only on manifest; updates only `last_checked_at` and the global `.version-cache.json`. |

## UpgradePlan (transient, CLI-side)

In-memory object built by `cmd_upgrade --all`, never persisted. Used to show the operator a single confirmation prompt summarizing what will change.

```python
@dataclass
class UpgradePlan:
    project_id: str
    project_path: Path
    tools: list[tuple[str, str, str]]  # (tool_name, from_version, to_version)
    skipped_pinned: list[tuple[str, str]]  # (tool_name, pinned_version)
```

Rendered:

```text
Upgrade plan for project dev:
  claude   2.1.150 → 2.1.151
  gh       2.94.0  → 2.95.0
Skipped (pinned):
  uv       0.4.10  (pinned)
Apply these upgrades? [y/N]
```

## VersionCache (single host-wide file)

Path: `$ASDD_HOME/_state/tools/.version-cache.json`. Shared across all projects (it's about *upstream* latest versions, not per-project state).

```json
{
  "entries": [
    { "tool_name": "claude", "latest_version": "2.1.151", "checked_at": 1749738850 },
    { "tool_name": "gh",     "latest_version": "2.95.0",  "checked_at": 1749738850 }
  ]
}
```

Cache rules:

- Entries older than 300 seconds are ignored on read.
- A successful probe overwrites the entry for that tool.
- A failed probe leaves the entry alone (so an offline operator keeps seeing the last-known-latest until they go back online).

## On-disk layout summary

```text
$ASDD_HOME/_state/tools/
├── .version-cache.json
└── <project_id>/
    ├── claude/
    │   ├── .lock                          # fcntl.flock target
    │   ├── manifest.json                  # see above
    │   ├── bin/                           # symlinks resolved into here
    │   │   └── claude → ../versions/2.1.151/bin/claude
    │   ├── versions/
    │   │   ├── 2.1.151/
    │   │   │   ├── bin/claude
    │   │   │   └── lib/node_modules/@anthropic-ai/claude-code/...
    │   │   └── 2.1.150/
    │   │       └── ...
    │   └── incoming/                       # transient; cleared on next upgrade
    ├── gh/
    │   └── ...
    └── uv/
        └── ...
```

`bin/` at the per-tool level is a small wrinkle: each tool has its own `bin/` that contains a single symlink. The container's PATH actually points at `~/.asdd-tools/bin/`, which is at the *overlay root*, not the per-tool root.

Resolution: a top-level `bin/` at `~/.asdd-tools/bin/` aggregates per-tool symlinks. On every upgrade, the CLI maintains the symlink `~/.asdd-tools/bin/<binary> → ../<tool>/versions/<ver>/bin/<binary>`. Simpler than rewriting PATH per tool.

Updated layout:

```text
$ASDD_HOME/_state/tools/<project_id>/
├── bin/                                   # aggregated; on PATH
│   ├── claude → ../claude/versions/2.1.151/bin/claude
│   ├── gh     → ../gh/versions/2.95.0/bin/gh
│   └── uv     → ../uv/versions/0.4.10/uv
├── claude/
│   ├── .lock
│   ├── manifest.json
│   ├── versions/<ver>/...
│   └── incoming/...
├── gh/...
└── uv/...
```

## Constraints + invariants

- Per-(project, tool) `.lock` MUST be held during all writes to that tool's subdirectory.
- The aggregate `bin/` symlinks MUST be updated atomically (via `ln -sfn` semantics) on every upgrade or rollback — never have a broken intermediate symlink.
- `incoming/` is treated as scratch; the CLI MUST be safe against a leftover `incoming/` from a prior crash (next upgrade overwrites it).
- The host bind mount maps `$ASDD_HOME/_state/tools/<project_id>/` to `/home/asdd/.asdd-tools/` inside the container. This means file modes set on the host are visible inside the container; the operator's uid 1000 on the host MUST own the overlay root. The asdd CLI sets these on first create.
- The version cache file (`.version-cache.json`) is also bind-mounted in (alongside the per-project subdir) at `/home/asdd/.asdd-tools/.version-cache.json` so the in-container claude can see "what was the latest known at the last host-side check." (Mostly informational; the host-side asdd CLI is the only writer.)

## Schema migration policy

This feature ships at `schema_version = 1`. Future migrations:

- A future version that adds a new optional field bumps to schema_version=2 only if old readers would misbehave (typically: no, additive fields are tolerated).
- A breaking change ships a new schema_version AND a migration in `asdd/tool_manifest.py` that reads the old shape and writes the new shape on first load. The migration MUST be atomic at the file level (write to `.tmp`, rename).

## Out-of-scope data shapes

- No record of `--reload` vs. non-`--reload` invocations. The history records what's installed, not how.
- No record of who ran the upgrade — single-operator assumption.
- No `installed_size_bytes_total` aggregate; computed on demand if a future feature needs it.
