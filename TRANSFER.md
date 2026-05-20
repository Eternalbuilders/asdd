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

## Spec location and dev/deploy model

Master specs live **outside this repo** in the ControlVault Obsidian
vault. Development happens inside a Linux devcontainer where the vault
is bind-mounted; deployment is to a Mac host where the same vault
exists at a different absolute path.

The repo's `specs/` symlink uses the **container-side path** so it
resolves at dev time:

```
<repo>/specs  ->  /vaults/ControlVault/Specs/asdd
                  (Mac equivalent: ~/Vaults/ControlVault/Specs/asdd)
```

On the Mac the symlink will dangle (no `/vaults/` mount), but that
doesn't matter — the asdd CLI itself never reads from `specs/` at
runtime. Schemas live in `asdd/contracts/`, project templates live in
`project_skeleton/`. `specs/` is purely a dev-time surface for
`/speckit-*` slash commands and human spec authoring, both of which
happen inside the container.

`make bundle` deliberately **excludes `specs/`** from the deploy
tarball — specs aren't install material.

This repo therefore has two natural environments:

| Environment | Where | What works |
| --- | --- | --- |
| Dev (in-container) | `/workspace/asdd-repo/` | Everything: code, tests, `specs/` symlink, `/speckit-*` slash commands |
| Deploy (Mac) | wherever the bundle gets unpacked | asdd CLI + container image build. No `specs/` symlink. |

## What was deliberately left behind

These siblings from the source monorepo were **not** carried over —
asdd doesn't import them:

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
