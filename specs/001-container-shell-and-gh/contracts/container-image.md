# Contract: project container image (`asdd/project:latest`)

**Feature**: 001-container-shell-and-gh
**Status**: Revised. Adds a profile.d snippet and bumps the `gh` pin.

## Purpose

The image continues to host both the interactive Claude session and the autonomous-mode runner. This feature adds:

1. An in-image bash hook that prepends `(<project>) ` to `PS1` if `ASDD_PROJECT_ID` is set.
2. A newer pinned `gh` version.

Nothing about the existing layers (Python, sops, uv, npm/Claude, the `asdd` user) changes.

## Build inputs (Dockerfile)

| Build arg / step | Before | After |
|---|---|---|
| `ARG GH_VERSION` | `2.92.0` | `2.94.0` (current stable) |
| `COPY docker/files/asdd-prompt.sh /etc/profile.d/asdd-prompt.sh` | absent | added, mode `0644` |
| Default CMD | `["bash"]` | `["bash"]` (unchanged) |

All other layers are byte-identical.

## Runtime inputs (env vars)

| Variable | Set by | Consumed by | Effect |
|---|---|---|---|
| `ASDD_PROJECT_ID` | `asdd open` and `asdd claude` via `start_container` `extra_env` | `/etc/profile.d/asdd-prompt.sh` at shell start | Prepends `(<value>) ` to `PS1` for interactive shells. |
| `ASDD_HOME` | Image `ENV` (existing) | asdd in-container CLI | Unchanged. |
| `HOME` | Image `ENV` (existing) | bash, claude, gh | Unchanged. |

## In-image artifact — `/etc/profile.d/asdd-prompt.sh`

```bash
# /etc/profile.d/asdd-prompt.sh
# Prepend "(project) " to PS1 when ASDD_PROJECT_ID is set so the operator
# always knows which project a shell is inside. No-op for non-interactive
# shells (dispatch, claude --print, etc.) so log output stays clean.

[[ $- == *i* ]] || return 0
[[ -n "${ASDD_PROJECT_ID:-}" ]] || return 0
case "$PS1" in
  "(${ASDD_PROJECT_ID}) "*) return 0 ;;
esac
PS1="(${ASDD_PROJECT_ID}) ${PS1}"
```

Properties:

- **Idempotent**: re-sourcing in a sub-shell is a no-op (the `case` guard catches the already-prefixed state).
- **Composes around the user's `PS1`** rather than replacing it.
- **Interactive-only**: dispatch-mode shells (no `i` in `$-`) and pipes are unaffected.

## `gh` install

The existing `gh` install block stays as-is except for the version bump:

```dockerfile
# GitHub CLI (gh) — for repo operations from inside the container.
# Bump this pin intentionally with each asdd minor release; do NOT
# float to `latest`.
ARG GH_VERSION=2.94.0
RUN ARCH="$(dpkg --print-architecture)" \
    && curl -fsSL -o /tmp/gh.tar.gz \
        "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${ARCH}.tar.gz" \
    && tar -xzf /tmp/gh.tar.gz -C /tmp \
    && install -m 0755 "/tmp/gh_${GH_VERSION}_linux_${ARCH}/bin/gh" /usr/local/bin/gh \
    && rm -rf /tmp/gh.tar.gz "/tmp/gh_${GH_VERSION}_linux_${ARCH}"
```

## Image smoke contract

The integration test asserts:

1. `docker run --rm asdd/project:latest gh --version` exits 0 and prints a string matching `gh version 2.94.*`.
2. `docker run --rm -e ASDD_PROJECT_ID=foo asdd/project:latest bash -lic 'echo "$PS1"'` includes the literal substring `(foo)`.
3. `docker run --rm asdd/project:latest bash -lic 'echo "$PS1"'` does NOT include any `(...)` prefix (no project set → no leakage).
4. `docker run --rm asdd/project:latest claude --version` exits 0 (existing assertion; no change).
5. `docker run --rm asdd/project:latest test -x /usr/local/bin/asdd-run-job` exits 0 (existing assertion; no change).

These tests skip cleanly when Docker is not available, matching the existing `tests/integration/` convention.

## Reproducibility

- Both `gh` and `sops` are version-pinned in `ARG` and downloaded from a deterministic URL; rebuilding the image at any future time produces a byte-for-byte identical layer for those steps.
- The profile.d script is a vendored repo file, not fetched from the network.

## What this contract explicitly does NOT change

- Base image (`python:3.12-slim`).
- The `asdd` user (UID 1000) and the `WORKDIR /asdd_home`.
- Any of the auth-mount expectations from spec 009 (`$ASDD_HOME/_state/claude-auth/` mounting).
- `CMD ["bash"]`. The default startup is still bash; this feature only customizes that bash's prompt.
- Any of the existing OS packages (`git`, `jq`, `less`, `nodejs`, `npm`, `ripgrep`, `sqlite3`, `tmux`, `vim-tiny`, `ca-certificates`, `curl`, `gnupg`).
