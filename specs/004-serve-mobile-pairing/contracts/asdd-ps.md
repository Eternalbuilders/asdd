# Contract — `asdd ps` output

## Scope

Adds a `PAIRED` column to `asdd ps`. No other CLI surface changes.

## Output shape

Before this feature:

```text
PROJECT          MODE        STATE       CONTAINER
hello-world      persistent  active      asdd-project-hello-world
demo-2           interactive active      asdd-project-demo-2
ingest-pipeline  -           active      -
```

After this feature:

```text
PROJECT          MODE        STATE       PAIRED         CONTAINER
hello-world      persistent  active      paired         asdd-project-hello-world
demo-2           interactive active      n/a            asdd-project-demo-2
ingest-pipeline  -           active      n/a            -
```

The new `PAIRED` column appears between `STATE` and `CONTAINER`. Values:

| Value | Meaning |
|---|---|
| `paired` | Serve container is up; `~/.claude/sessions/<pid>.json` has a non-empty `bridgeSessionId` and `updatedAt` within the last 60 seconds. Mobile app should see this session. |
| `unpaired` | Serve container is up but no `bridgeSessionId` is present (session JSON missing or `bridgeSessionId` empty/null). Likely: handshake not yet completed, or pairing-service unreachable. |
| `reconnecting` | `bridgeSessionId` is present but the session JSON hasn't been updated in over 60 seconds. Likely: transient network loss, Claude is re-establishing. |
| `n/a` | Project has no running persistent (serve) container. Interactive and autonomous modes do not show pairing status. |

## Behavioural contract

- `asdd ps` MUST NOT block on a network call to derive the `PAIRED` column. The derivation is filesystem-only.
- `asdd ps` MUST NOT alter any state to derive the column.
- If reading the session JSON fails (file present but unparseable, or `docker exec` to read it returns non-zero), the column reports `unpaired` with no stack trace.
- Performance: total `asdd ps` runtime MUST NOT exceed 2 seconds for ≤20 projects on a warm Docker (R1 — derivation is one `docker exec cat` per running serve, parallelizable).

## JSON output

`asdd ps --json` (existing flag) gains a `paired` field per row, with values `"paired"`, `"unpaired"`, `"reconnecting"`, or `"n/a"`. Pre-existing JSON consumers ignore unknown fields, so this is additive.

## Unit test contract

| Test | Expected |
|---|---|
| `_pairing_state` against a project with no container | `"n/a"` |
| `_pairing_state` against a serve container with no session JSON | `"unpaired"` |
| `_pairing_state` against a serve container whose session JSON has `bridgeSessionId: ""` | `"unpaired"` |
| `_pairing_state` against a serve container whose session JSON has a non-empty `bridgeSessionId` and recent `updatedAt` | `"paired"` |
| `_pairing_state` against a serve container whose session JSON has `bridgeSessionId` but `updatedAt` is >60s old | `"reconnecting"` |
| `_pairing_state` is purely a filesystem read — no network call | (assert by mocking; spy on subprocess.run for docker only) |
