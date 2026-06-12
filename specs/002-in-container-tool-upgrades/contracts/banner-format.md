# Contract: Session-start stale-tool banner

**Feature**: 002-in-container-tool-upgrades
**Status**: New.
**Location**: `asdd/banner.py` (renderer) + integration in `asdd/bootstrap.py:cmd_open`, `cmd_claude`, `cmd_serve`.

## When the banner runs

Before the attach in any of:

- `asdd open <project>`
- `asdd claude <project>`
- `asdd serve <project>` (only on the foreground operator's run; not on launchd-supervised relaunches — those are background and would just spam stderr with no operator to read)

## When it suppresses

- The version cache is fresh and reports the tool current. (No I/O at all.)
- The check times out. (Silent — the operator never waits longer than 2s for the check.)
- The tool is pinned at the current_version. (No prompt to upgrade what they deliberately froze.)
- `NO_BANNER=1` is set in the operator's env.
- `--quiet` is passed to the command.

## The banner line

```text
⓿  <tool> <from> → <to> available — run `asdd upgrade <tool> <project>` to apply
```

Concretely:

```text
⓿  claude 2.1.150 → 2.1.151 available — run `asdd upgrade claude dev` to apply
```

Length cap: ≤ 78 columns. If the rendered line would exceed 78 columns, drop the `→ <to>` middle clause:

```text
⓿  claude — update available — run `asdd upgrade claude dev` to apply
```

## Colorization

When stdout is a TTY and `NO_COLOR` is unset:

- `⓿` and the command-to-run (`asdd upgrade ...`) → ember (`\x1b[33m`).
- `available` → bold (`\x1b[1m`).
- Everything else → default.

Pipe-safe: when stdout is not a TTY (or `NO_COLOR` is set), emit no escapes.

## Multiple-tool case

One line per stale tool, in alphabetical order. Maximum of 5 lines shown; if more than 5 tools are stale, the 6th+ are folded into a final summary line:

```text
⓿  claude 2.1.150 → 2.1.151 available — run `asdd upgrade claude dev` to apply
⓿  gh 2.94.0 → 2.95.0 available — run `asdd upgrade gh dev` to apply
⓿  uv 0.4.10 → 0.4.12 available — run `asdd upgrade uv dev` to apply
⓿  4 more tools have updates — run `asdd versions dev` to see them
```

## Placement

The banner prints to stderr (not stdout) so it doesn't contaminate scripted output. A blank line separates it from the attach-in-progress text:

```
asdd: opening project dev
asdd: container asdd-project-dev is running

⓿  claude 2.1.150 → 2.1.151 available — run `asdd upgrade claude dev` to apply

asdd: attaching...
```

## Performance

- Cache hit (everything fresh): zero network, < 50ms.
- Cache miss / partial: parallel probes, ≤ 2s wall-clock.
- Total budget before attach: ≤ 2s.

The asdd CLI must NEVER hold up the attach for longer than 2s due to version checks. If the deadline is hit with checks still in flight, the banner emits whatever results it has and the rest are dropped (silently — no "check timed out" noise in the banner itself).

## What the banner does NOT include

- No release notes / changelog. The banner is one line; the operator opens the upstream release page if they want details.
- No "this update fixes a security issue" annotation. That requires upstream metadata we don't fetch.
- No "you're 5 versions behind" telemetry. Just current → latest.
- No suggestions to upgrade multiple tools at once. The bulk-upgrade command exists separately; the banner is per-tool.
