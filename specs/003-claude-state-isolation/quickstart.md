# Quickstart — 003-claude-state-isolation validation

Operator-facing runbook to verify the feature end-to-end. Run on a Mac host with a real `asdd` install (per the dev/deploy split in CLAUDE.md, the dev container can run the same flows against a scratch `$ASDD_HOME`).

## Prerequisites

- `asdd` installed (`pipx install --editable .` from a checkout of this branch)
- Docker available on `PATH`
- Two distinct project IDs to create — call them `iso-a` and `iso-b`
- A scratch `$ASDD_HOME` (e.g. `mktemp -d`) to avoid touching real state during validation; or accept that an existing login will be reused

## 1. Project A leaves a transcript; Project B does not see it (FR-001, SC-001)

```bash
# create both projects
asdd project create iso-a
asdd project create iso-b

# one-shot login if needed
asdd login --seed   # or --fresh

# write a sentinel transcript file via project A's container
# (we don't need a real Claude session — touching the path is enough to prove isolation)
asdd open iso-a
mkdir -p ~/.claude/projects/-asdd-home
echo '{"sentinel":"from-iso-a"}' > ~/.claude/projects/-asdd-home/sentinel.jsonl
exit

# check that project B's container does not see it
asdd open iso-b
ls ~/.claude/projects/-asdd-home/ 2>/dev/null || echo "DIR-ABSENT-OR-EMPTY"
exit
```

**Expected**: in project B, the listing prints `DIR-ABSENT-OR-EMPTY` (or shows files written only by project B itself). The sentinel from A is NOT visible. Inspect host side as confirmation:

```bash
ls $ASDD_HOME/_state/claude-auth/per-project/iso-a/projects/-asdd-home/
# → sentinel.jsonl

ls $ASDD_HOME/_state/claude-auth/per-project/iso-b/projects/-asdd-home/ 2>/dev/null || echo "B-empty"
# → B-empty
```

## 2. Shared credential surface (FR-002, FR-003, SC-002, SC-003)

```bash
# inspect the credential file from inside project A's container
asdd open iso-a
ls -la ~/.claude/.credentials.json     # SHARED — file bind mount
ls -la ~/.claude.json                  # SHARED — file bind mount
exit

# do the same from project B; same content, same inode (from host's perspective)
asdd open iso-b
ls -la ~/.claude/.credentials.json
exit

# host-side: confirm both containers' .credentials.json mounts resolve to the same host file
ls -i $ASDD_HOME/_state/claude-auth/claude/.credentials.json
```

**Expected**: both containers see the same `.credentials.json` content (single shared host file). Sizes and mtimes match.

## 3. Removing a project removes its per-project state (FR-005, SC-004)

```bash
# project A had a sentinel; confirm host directory exists
test -d $ASDD_HOME/_state/claude-auth/per-project/iso-a && echo "A-state-exists"

# remove project A
asdd project remove iso-a   # or whichever command-name lifecycle.py exposes

# confirm A's per-project state is gone, B's is untouched
test -d $ASDD_HOME/_state/claude-auth/per-project/iso-a || echo "A-removed"
test -d $ASDD_HOME/_state/claude-auth/per-project/iso-b && echo "B-intact"
```

**Expected**: `A-state-exists`, then `A-removed`, then `B-intact`.

## 4. `asdd logout` clears everything (FR-006)

```bash
asdd logout
test -d $ASDD_HOME/_state/claude-auth || echo "ALL-CLEARED"
```

**Expected**: `ALL-CLEARED`. Per-project state for every remaining project is gone; the shared credential surface is gone. Next `asdd open <project>` triggers a fresh login.

## 5. Migration notice on first post-upgrade container start (FR-009, SC-005)

Simulate the pre-upgrade layout:

```bash
# fresh ASDD_HOME, seeded credentials but no per-project layout yet
asdd login --seed

# place legacy-layout mixed transcripts under the shared store
mkdir -p $ASDD_HOME/_state/claude-auth/claude/projects/-asdd-home
echo '{"legacy":"mixed-history"}' \
  > $ASDD_HOME/_state/claude-auth/claude/projects/-asdd-home/legacy.jsonl
test -e $ASDD_HOME/_state/claude-auth/.migration-notice-shown && rm \
  $ASDD_HOME/_state/claude-auth/.migration-notice-shown

# first project start should emit the one-time notice
asdd project create iso-c
asdd open iso-c     # observe the one-line migration notice on stderr
exit

# second start should NOT re-emit
asdd open iso-c | grep -i "migration" && echo "BUG: notice re-emitted" || echo "notice-not-re-emitted"
```

**Expected**: first `asdd open iso-c` prints the notice on stderr; second `asdd open iso-c` does not. The marker file `$ASDD_HOME/_state/claude-auth/.migration-notice-shown` exists after the first run.

## 6. Persistent-session keeps its own history across restarts (FR-004, SC-006)

```bash
# persistent session for project A
asdd project create iso-d
asdd serve start iso-d

# write a sentinel from inside the supervised container
docker exec -it asdd-project-iso-d bash -c \
  'mkdir -p ~/.claude/projects/-asdd-home && echo serve-sentinel > ~/.claude/projects/-asdd-home/serve.txt'

# trigger restart via the supervisor
asdd serve restart iso-d

# verify the sentinel survived
docker exec -it asdd-project-iso-d cat ~/.claude/projects/-asdd-home/serve.txt
# → serve-sentinel

asdd serve stop iso-d
```

**Expected**: the sentinel survives the restart. The persistent session sees its own history across the launchd-driven restart cycle.

## Done When

- All six sections execute as documented
- Host-side `_state/claude-auth/` matches the layout in `data-model.md`
- No cross-project leakage observable from inside containers
