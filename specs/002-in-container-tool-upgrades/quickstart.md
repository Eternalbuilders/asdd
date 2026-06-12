# Quickstart: Keep your tools current

**Feature**: 002-in-container-tool-upgrades
**Audience**: An asdd operator who wants to keep `claude`, `gh`, `uv` (and anything we add later) at the latest version inside their project containers.

This recipe assumes you have asdd installed, at least one project registered, and Docker running.

## The 30-second loop

```bash
# See what's installed and what's available.
asdd versions dev

# Upgrade one tool. Default: install the new binary; running Claude stays on the old one.
asdd upgrade claude dev

# Upgrade and bounce the running Claude so the conversation resumes in the new version.
asdd upgrade claude dev --reload

# Roll back if the new version misbehaves.
asdd rollback claude dev

# Pin a tool to its current version (reproducibility lock).
asdd pin claude=2.1.150 dev

# Remove the pin.
asdd unpin claude dev

# Wipe the per-project overlay; the image baseline takes over on next session.
asdd reset-tools claude dev
asdd reset-tools --all dev
```

You never need to remember a `docker` command.

## What happens at session start

When you run `asdd open dev`, `asdd claude dev`, or foreground `asdd serve dev`, asdd does a quick (≤ 2 s) version check on every managed tool. If any are stale, you see one line per tool before the attach, naming the exact command to apply the upgrade:

```text
⓿  claude 2.1.150 → 2.1.151 available — run `asdd upgrade claude dev` to apply

asdd: attaching...
```

Nothing is upgraded silently. You always type the command.

To suppress the check for one invocation: `NO_BANNER=1 asdd open dev` or `asdd open dev --quiet`.

## Where the upgrades live (host)

Per-project, plain files:

```text
$ASDD_HOME/_state/tools/
├── .version-cache.json
└── dev/
    ├── bin/                  # what container PATH points at
    │   └── claude → ../claude/versions/2.1.151/bin/claude
    └── claude/
        ├── manifest.json
        ├── versions/2.1.151/...   # current
        ├── versions/2.1.150/...   # retained for rollback
        └── upgrade.log
```

You can `cat`, `tar`, `du`, `ls` any of this. There's no hidden state.

## Inside the container

PATH is `~/.asdd-tools/bin:/opt/asdd-baseline/bin:/usr/local/bin:/usr/bin:/bin`. Your per-project overlay wins; the image's baseline catches everything else.

If you `rm -rf ~/.asdd-tools/<tool>/` (or run `asdd reset-tools`), the baseline takes over silently on next session.

## End-to-end validation scenarios

These are the scenarios `tests/integration/test_upgrade_e2e.py` runs against a real Docker container. They're also good first-time smoke tests for an operator on their Mac.

### Scenario 1: Upgrade `claude` in a fresh project

Prereqs: project `dev` exists; container is running.

1. `asdd versions dev` — note current `claude` version.
2. `asdd upgrade claude dev` — wait < 30 s.
3. Re-run `asdd versions dev` — `claude` row shows the new version.
4. `docker exec asdd-project-dev claude --version` confirms the new version.
5. `cat $ASDD_HOME/_state/tools/dev/claude/manifest.json` — `current_version` matches, `history` has 1 entry, `pin` is null.

### Scenario 2: Upgrade survives container recreation

1. Upgrade `claude` (scenario 1).
2. `asdd stop dev`; wait for launchd to relaunch (or `asdd serve dev`).
3. `docker exec asdd-project-dev claude --version` — STILL the upgraded version.

### Scenario 3: Banner appears on stale tool

1. Manually downgrade `claude`: `asdd rollback claude dev`. Now you're behind.
2. `asdd open dev` — banner appears with `claude — update available — run …` line before attach.

### Scenario 4: `--reload` resumes the conversation

1. With a persistent `asdd serve dev` running and a Claude conversation in progress.
2. `asdd upgrade claude dev --reload`.
3. Within ~5 seconds the tmux session reconnects via `claude --continue`. The conversation is intact. Footer shows the new version. `Remote Control active` reappears.

### Scenario 5: Pinned tool is skipped by bulk upgrade

1. `asdd upgrade claude dev` (to latest).
2. `asdd pin claude=<that version> dev`.
3. Publish a newer claude upstream (or wait).
4. `asdd upgrade --all dev`. Confirmation prompt shows `Skipped (pinned): claude (pinned)`.

### Scenario 6: Reset returns to baseline

1. Upgrade `claude` to a non-baseline version.
2. `asdd reset-tools claude dev`.
3. `docker exec asdd-project-dev claude --version` — back to the image baseline.

### Scenario 7: Rollback the most recent upgrade

1. `claude --version` shows `2.1.151`.
2. `asdd rollback claude dev`.
3. `claude --version` now shows `2.1.150`.
4. `asdd rollback claude dev` again. Back to `2.1.151`. (Rollback is symmetric — the operator can flip between the two retained versions.)

## First-time provisioning (one-time)

The first deploy of the spec-002 image needs:

```bash
# In the asdd repo (the dev side or a deploy machine):
git pull
docker build --no-cache -f docker/Dockerfile.project -t asdd/project:latest .

# Stop and recreate every project's container so they pick up the new image.
asdd ps
asdd stop <each id>
docker rm <each container>
asdd serve <each id>
```

After that, future upgrades use `asdd upgrade <tool> <id>` — no image rebuild ever needed for tool versions.

## Failure modes & recovery

| Symptom | Likely cause | Fix |
|---|---|---|
| `asdd upgrade` exits 4 with "registry unreachable" | Network down or upstream registry slow. | Try again. Until then, the prior version stays live. |
| `asdd upgrade` exits 2 with "already in progress" | Two terminals tried to upgrade the same tool at once. | Wait a moment; retry. |
| `asdd upgrade --reload` returns exit 5 | Tmux/supervisor restart failed (rare; e.g. container lost network mid-bounce). | The new binary IS installed; just run `asdd stop <id>` (launchd will relaunch) or `asdd open <id>` to verify state. |
| Tester reports "still on old version after upgrade" | The running Claude has the old binary in memory. | Tell them to run `/clear` in Claude, or run `asdd upgrade claude <id> --reload`. |
| `asdd reset-tools` says "no overlay state" | Nothing to reset; tool is already at baseline. | Treat as success. |
| Container shows the old image's claude after rebuild | Container is still using the prior image. | `asdd stop <id>` + `docker rm asdd-project-<id>` + `asdd serve <id>`. |

## Constitution callbacks

- All overlay state is plain files (`II. Plain Files Where Humans Read State`). You can `cat manifest.json`.
- Single writer (`III. Single Writer per File`) — only the asdd CLI writes; the file lock enforces it.
- Container-portable (`IV. Container-Portable Runtime`) — no new host-OS dependency; banner runs as part of asdd CLI which is portable.
- No new secrets (`V. Secret Hygiene`) — public-registry reads only.
