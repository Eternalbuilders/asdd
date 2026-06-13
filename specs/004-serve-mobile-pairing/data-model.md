# Data Model — 004-serve-mobile-pairing

This feature does not introduce any new files asdd owns. It reads one Claude-Code-owned file inside the container and uses its content to derive a new column in `asdd ps`.

## Read-only dependency: Claude Code session file

Per R1, Claude Code 2.1.175 writes one JSON file per running session at:

```text
~/.claude/sessions/<pid>.json
```

…which is mapped on the host to (under the spec 003 per-project subtree):

```text
$ASDD_HOME/_state/claude-auth/per-project/<project_id>/sessions/<pid>.json
```

Shape (only fields asdd reads):

| Field | Type | Meaning for this feature |
|---|---|---|
| `pid` | int | The Claude process PID inside the container. Used to disambiguate when more than one session file exists. |
| `cwd` | string | The session's working directory. For serve sessions this is always `/asdd_home`. Used to filter to "this project's serve session". |
| `kind` | string | `"interactive"` for serve sessions. Filter target. |
| `entrypoint` | string | `"cli"` for serve sessions. Filter target. |
| `bridgeSessionId` | string \| null | Non-empty when the session is currently paired with claude.ai. **This is the truth signal for the "paired" column in `asdd ps`.** |
| `name` | string | Operator-visible display name (set via `--name` on serve startup). |
| `updatedAt` | int (ms) | Last write timestamp. Used to detect stale files. |

asdd treats every field as opaque except as listed; future Claude-Code field additions are tolerated without code changes.

## Entity: Paired serve session

Conceptual entity surfaced in operator-facing output. Not persisted by asdd; derived on demand.

| Attribute | Source | Notes |
|---|---|---|
| `project_id` | asdd registry | The project this session belongs to. |
| `pairing_state` | derived | One of `paired` / `unpaired` / `reconnecting` / `n/a` (project has no serve). |
| `pairing_id` | session JSON `bridgeSessionId` | Shown in verbose `asdd ps` modes; truncated. |
| `session_pid` | session JSON `pid` | Diagnostics only. |

## Pairing-state derivation

```text
no serve container running                   → n/a
serve container running, no session JSON     → unpaired (Claude has not yet started a session)
serve container running, session JSON
    has empty/missing bridgeSessionId        → unpaired
serve container running, session JSON
    has bridgeSessionId, updatedAt < 60s ago → paired
serve container running, session JSON
    has bridgeSessionId, updatedAt > 60s ago → reconnecting   (Claude has the field but hasn't refreshed
                                                                recently — likely lost the bridge connection)
```

The 60-second window for `reconnecting` matches the spec's SC-002 / SC-003 bounds: a session that hasn't refreshed in over 60 seconds is treated as actively reconnecting, not paired. This avoids `asdd ps` showing a stale "paired" while the operator's mobile app sees nothing.

## State machine (per project's serve session)

```text
                  asdd serve <id>
                       │
                       ▼
              ┌───────────────────┐
              │ container up,     │
              │ no session JSON   │  (transient — Claude hasn't started yet)
              └────────┬──────────┘
                       │ claude writes session JSON
                       ▼
              ┌───────────────────┐
              │   unpaired        │  (no bridgeSessionId yet)
              └────────┬──────────┘
                       │ Claude completes bridge handshake
                       ▼
              ┌───────────────────┐         ┌────────────────┐
              │    paired         │ ───▶    │ reconnecting   │
              │                   │ ◀───    │                │
              └────────┬──────────┘         └────────────────┘
                       │                          (updatedAt > 60s ago,
                       │ container exits           bridgeSessionId still
                       ▼                           present)
              ┌───────────────────┐
              │       n/a         │
              │ (back to start    │
              │  via supervisor)  │
              └───────────────────┘
```

Transitions are observed, never written by asdd. asdd only reads the session JSON and the container's running state.

## Boundaries

- **In scope**: reading the session JSON inside the container; surfacing `paired` in `asdd ps`; using `bridgeSessionId` presence as truth.
- **Out of scope**: writing or modifying the session JSON; opening a watchdog that polls pairing on the host; reaching the Anthropic bridge API directly.
