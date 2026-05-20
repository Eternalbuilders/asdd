# Extraction notes

This repository was extracted from `github.com/Eternalbuilders/VaultControl`
(the `controlvault-agent` monorepo) on 2026-05-20.

## What came across

- `asdd/` Python package (the CLI and per-project container manager)
- `docker/Dockerfile.project` + `docker/files/asdd-run-job.sh` (slimmed)
- Schemas formerly at `specs/007-asdd-architecture/contracts/`, now at
  `asdd/contracts/` (inside the package)
- Project workspace skeleton, formerly `controlvault-skeleton/_templates/`,
  now `project_skeleton/`
- Tests: `tests/unit/test_asdd_*`, `tests/integration/test_open_*`,
  `tests/integration/test_dispatch_*`, plus shared fixtures
- Spec docs for 007 (architecture) and 008 (per-project containers) —
  moved out of the repo entirely to the master vault location (see below)

## Renames applied at extraction

| Before                                  | After                              |
| --------------------------------------- | ---------------------------------- |
| `controlvault-skeleton/_templates/`     | `project_skeleton/`                |
| `specs/007-asdd-architecture/contracts/`| `asdd/contracts/`                  |
| Image tag `controlvault/project:latest` | `asdd/project:latest`              |
| Container name `controlvault-project-…` | `asdd-project-…`                   |
| Package name `controlvault-agent`       | `asdd`                             |

## Spec location

Master specs live **outside this repo** at
`/Users/marius/Vaults/ControlVault/Specs/asdd/` (inside the existing
ControlVault Obsidian vault). The repo exposes them via a symlink:

```
<repo>/specs -> /Users/marius/Vaults/ControlVault/Specs/asdd/
```

That symlink is committed, so worktrees inherit it. Spec content is
never touched by git operations on this repo — only the symlink itself
is.

If you clone this repo on a different machine, the symlink will dangle
until you create the master spec directory at the same path (or change
the symlink target). For now this is single-Mac portable by design.

## What was deliberately left behind

These siblings from the source monorepo were **not** carried over —
`asdd` doesn't import them and doesn't need them:

- `kernel/` `agents/` `dashboards/` `browser_runner/`
- `specs/001-…/contracts/`, `specs/002-…/contracts/`, `specs/005-…/contracts/`
- All non-asdd tests
- `.specify/`, `.devcontainer/`, `scripts/`, etc.

## What still lives upstream

The source `vaultcontrol` repo still contains its own copy of `asdd/`,
plus `specs/007-…/` and `specs/008-…/`. That's intentional — this
extraction is additive. The upstream copies can be removed later once
this repo is established as the source of truth.

## Git history

Fresh `git init`. No filter-repo'd history. The original commits that
touched asdd are still in the upstream repo if archaeology is needed.
