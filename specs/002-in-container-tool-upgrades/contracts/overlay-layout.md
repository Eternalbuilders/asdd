# Contract: On-disk overlay layout

**Feature**: 002-in-container-tool-upgrades
**Status**: New.

## Host side

```text
$ASDD_HOME/_state/tools/
├── .version-cache.json                   # one file; shared across projects
└── <project_id>/                         # per-project; created on first upgrade
    ├── bin/                              # aggregated symlinks; this is what PATH points at
    │   ├── claude → ../claude/versions/2.1.151/bin/claude
    │   ├── gh     → ../gh/versions/2.95.0/bin/gh
    │   └── uv     → ../uv/versions/0.4.10/uv
    └── <tool_name>/                      # one subdir per tool that's been touched
        ├── .lock                         # fcntl.flock target; empty file
        ├── manifest.json                 # per-tool state; see data-model.md
        ├── upgrade.log                   # append-only log of upgrade actions
        ├── versions/
        │   ├── <ver>/                    # the actual install tree per version
        │   │   └── ...                   # driver-specific layout
        │   └── <prior_ver>/              # retained for rollback
        ├── incoming/                      # transient; cleared on every upgrade start
        │   └── <ver>/                    # in-progress install
        └── baseline-snapshot.txt          # written first time a tool is upgraded;
                                           # records the baseline version the operator
                                           # is "diverging from" — informational only
```

Ownership: every file and directory created under `$ASDD_HOME/_state/tools/<project_id>/` is owned by the host uid that runs the asdd CLI, which is the same uid (1000) the container runs as. This is what makes the bind mount work cleanly without `chown` games.

Permissions:
- Directories: `0700` (operator only).
- Files: `0600` (operator only).
- `bin/<tool>` symlinks: default symlink perms.

## Container side

The host's `$ASDD_HOME/_state/tools/<project_id>/` is bind-mounted into the container at:

```text
/home/asdd/.asdd-tools/
```

Inside the container, this directory looks identical to its host counterpart. PATH is:

```text
PATH=/home/asdd/.asdd-tools/bin:/opt/asdd-baseline/bin:/usr/local/bin:/usr/bin:/bin
```

The `/opt/asdd-baseline/bin/` floor catches any tool whose overlay is empty (per-project state has never been written) or whose overlay was reset.

## Driver-specific layouts under `versions/<ver>/`

### `npm-global` (claude)

```text
versions/<ver>/
├── bin/
│   └── claude                            # symlinked from $TOOL_ROOT/bin/claude
├── lib/
│   └── node_modules/
│       └── @anthropic-ai/
│           └── claude-code/
│               ├── package.json
│               └── ...
└── etc/                                  # if npm puts anything here
```

This matches the standard `npm install -g --prefix=<X>` layout. The driver invokes `npm install -g --prefix=$ASDD_TOOL_INCOMING_DIR @anthropic-ai/claude-code@<ver>` then renames `$ASDD_TOOL_INCOMING_DIR/<ver>/` to `$TOOL_ROOT/versions/<ver>/`.

### `github-release` (gh)

```text
versions/<ver>/
└── bin/
    └── gh                                # extracted from the upstream tarball
```

The driver downloads the platform-appropriate asset (`gh_<ver>_linux_amd64.tar.gz` or `gh_<ver>_linux_arm64.tar.gz`) into `incoming/<ver>/dl.tar.gz`, extracts the `bin/gh` from it into `incoming/<ver>/bin/gh`, and renames the dir.

### `astral-install` (uv)

```text
versions/<ver>/
└── uv                                    # single static binary
```

The driver runs `UV_INSTALL_DIR=$INCOMING_DIR sh <(curl -fsSL https://astral.sh/uv/install.sh)` (or fetches the corresponding GitHub release tarball directly — TBD in implementation; the GitHub-release-tarball path is simpler and avoids running a remote shell script every upgrade).

## Lifecycle: empty overlay

When `<project_id>/` doesn't exist on the host, the bind mount provides an empty dir inside the container. PATH falls through to `/opt/asdd-baseline/bin/`. The first run of `asdd upgrade <tool>` creates the directory tree.

## Lifecycle: cleared by `asdd reset-tools`

`asdd reset-tools <tool> <project>` rm-rfs `<project_id>/<tool>/` and removes `<project_id>/bin/<tool>`. Once removed, the next path resolution falls through to baseline.

## Backup story

The operator can:

```bash
tar czf my-tools-backup.tgz -C $ASDD_HOME/_state/tools .
```

Restore is the inverse. No version of asdd is required to read the layout — the operator can `cat manifest.json | jq` from any shell.

## Inspection from the host

All of these work without entering the container:

```bash
ls $ASDD_HOME/_state/tools/dev/                                # what tools exist
cat $ASDD_HOME/_state/tools/dev/claude/manifest.json | jq      # state for one tool
du -sh $ASDD_HOME/_state/tools/dev/*/versions/                 # space per tool
ls -la $ASDD_HOME/_state/tools/dev/bin/                        # current symlink targets
tail -50 $ASDD_HOME/_state/tools/dev/claude/upgrade.log        # upgrade history
```

## Lock convention

`.lock` is empty. It's acquired with `fcntl.flock(fd, LOCK_EX | LOCK_NB)` (non-blocking exclusive). On `EWOULDBLOCK`, the CLI returns exit 2 with a message.

The lock is RELEASED on:
- Normal exit (the file descriptor is closed).
- Crash (the kernel releases when the process dies).

It is NOT released on a stuck-in-IO command — that would block indefinitely. The CLI sets a 5-minute install timeout to prevent this.
