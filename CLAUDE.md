# CLAUDE.md — orientation for Claude working on the asdd repo

This file is for Claude sessions opened inside this repo. If you're a
human reader, `README.md` is the right starting point.

## What this repo is

The asdd CLI and its per-project container manager — extracted from
`Eternalbuilders/VaultControl` on 2026-05-20. Standalone now;
development happens here. See `TRANSFER.md` for the extraction story.

asdd has two operating modes:
- **Interactive**: `asdd open <id>` → bash shell inside the project's
  container, with the operator's `~/.claude/` auth bind-mounted.
- **Autonomous**: `asdd dispatch <id> <job.md>` → runs one markdown
  job-note through `claude --print` and writes the result. Uses
  `ANTHROPIC_API_KEY`; never mounts operator subscription auth.

The CLI is at `asdd/bootstrap.py` (Click command tree). The container
lifecycle is at `asdd/project_container.py`.

## Where this repo lives

- **Dev (here)**: `/workspace/asdd-repo/` inside this Linux devcontainer.
  All editing, testing, /speckit-* slash commands happen here.
- **Deploy**: `make bundle` produces `asdd-bundle.tar.gz` (~35 KB). The
  tarball is unpacked on a Mac at `~/asdd/` (or similar) and installed
  via `pipx install --editable .`. The Mac runs `asdd` against
  `$ASDD_HOME` projects. **The Mac doesn't run this dev workflow** —
  it's purely a deploy target.

Do **not** assume you can develop from the Mac side. Edits, tests, spec
work all happen inside this container.

## Layout

```
asdd/                  # the CLI package
├── bootstrap.py       # Click commands: init/new/list/open/close/dispatch/etc.
├── project_container.py  # docker run/build/exec wrappers
├── _schemas.py        # loads asdd/contracts/ at import time
├── contracts/         # JSON schemas (in-package data, NOT in specs/)
├── registry.py        # projects.yml I/O
├── secrets.py         # SOPS+age per-project secrets
├── audit.py           # audit log
└── lifecycle.py       # pause/resume/archive state machine
docker/
├── Dockerfile.project # asdd/project:latest — operator + dispatch image
└── files/asdd-run-job.sh   # in-container job runner shim
project_skeleton/      # scaffold copied into every new project at `asdd new`
specs -> /vaults/ControlVault/Specs/asdd/   # symlink to vault (master)
tests/                 # unit + integration; integration tests are @docker
pyproject.toml         # name=asdd, deps: PyYAML, jsonschema, click
Makefile               # install / test / lint / bundle / clean
README.md  USER_GUIDE.md  TRANSFER.md
```

## Daily commands

```bash
cd /workspace/asdd-repo
make test              # pytest; docker-tagged tests auto-skip if no daemon
make lint              # ruff check
make bundle            # produce asdd-bundle.tar.gz for transport to Mac
make clean             # drop bundle + caches

# Run the CLI in-place for ad-hoc testing
PYTHONPATH=. python3.12 -m asdd.bootstrap --help
```

## Specs and the vault symlink

The `specs/` directory is a **symlink to the ControlVault Obsidian vault**
at `/vaults/ControlVault/Specs/asdd/`. The master spec docs (007, 008,
and any future ones) live in the vault, not in git. The symlink:

- Resolves transparently in this container — `ls specs/`, `cat
  specs/007-asdd-architecture/spec.md`, `/speckit-*` slash commands all
  work as if the specs were inside the repo.
- Dangles on the Mac side — fine, because runtime asdd never reads
  `specs/`. Schemas live in `asdd/contracts/`, project templates in
  `project_skeleton/`.
- Is **excluded** from `make bundle` deliberately.

When you author or revise specs, edit through the symlink. Changes are
immediately visible in Obsidian. There is no separate "spec checkout"
step — the vault IS the canonical store.

## Invariants — do not regress

These were settled at extraction time. Changing them without explicit
user direction is a regression.

| Invariant | Where | Why |
| --- | --- | --- |
| Image tag is `asdd/project:latest` | `asdd/project_container.py:24` | Renamed from `controlvault/project:latest` at extraction. |
| Container prefix is `asdd-project-` | same file:25 | Match image tag. |
| Schemas at `asdd/contracts/`, not in `specs/` | `asdd/_schemas.py` | "No spec-named paths in the deployed bundle" — user requirement. |
| Skeleton at `project_skeleton/`, not `controlvault-skeleton/` | `asdd/bootstrap.py:40` | Same reason. |
| Bundle excludes `specs/` | `Makefile:bundle` | Symlink is dev-only; would dangle in any tarball. |
| Three deps only: PyYAML, jsonschema, click | `pyproject.toml` | Slimming was deliberate — kept asdd lean. Adding deps needs justification. |
| Tests pass before commit | `make test` | 53 unit tests; integration tests skip cleanly when docker isn't available. |

## Working with the user

The user is Marius (marius@froisland.no). Conventions that apply across
their projects, also relevant here:

- **Be terse**. State results, then stop. Don't trail with summaries.
- **Stepwise walkthroughs**: when guiding through multi-step setup or
  testing on the Mac, present **one step at a time**, wait for the
  result, then move on. Don't dump a full checklist.
- **Mac command clarity**: when asking the user to run a command on
  their Mac, lead with one short labelled sentence naming the command
  and the output to paste back. Example: "Run this on your Mac and
  paste the final summary line: `python3 -m pytest ...`"
- **No emojis** in files or messages unless asked.
- **Commits**: short summary line, body explains *why* (not what — the
  diff shows that). Co-Authored-By trailer with the model name.
- **Never** use `sudo`, install global packages on the user's host
  without asking, force-push to remote, or skip git hooks
  (`--no-verify`).

## Relationship to the source repo

The source `vaultcontrol` monorepo (at
`/workspace`, branch `017-test-prod-clarity`) still contains its own
copy of `asdd/`, `specs/007-…/`, and `specs/008-…/`. That copy is
**frozen as of 2026-05-20** from asdd's perspective — this repo is now
the source of truth. The user will eventually remove the old copies
from vaultcontrol, but only after confirming this repo is healthy.

If you find yourself wanting to make a change in
`/workspace/asdd/`, that's the wrong tree — make it here in
`/workspace/asdd-repo/asdd/` instead.

## Where to push (eventually)

Not pushed anywhere yet. When the user is ready:

```bash
cd /workspace/asdd-repo
gh repo create asdd --private --source=. --remote=origin --push
```

Owner can be `Eternalbuilders/` (their org, used for vaultcontrol) or
personal — ask.

## Open follow-ups (as of 2026-05-20)

- Push to a remote.
- Decide whether to delete `asdd/` and `specs/007-…/`, `specs/008-…/`
  from the `vaultcontrol` repo once this one is stable.
- Decide whether to set up a CI gate (`make pr-check` analog from
  vaultcontrol's spec 017) for this repo.
- The kernel→asdd dispatch integration (vaultcontrol's spec 007 US3/US4)
  is still deferred. If revived, decide whether kernel calls asdd as a
  subprocess or imports it as a Python package.

## Pointers

- `README.md` — user-facing install + workflow summary
- `USER_GUIDE.md` — full operator path (projects, dispatch, scheduling)
- `TRANSFER.md` — what came across, what got renamed, design rationale
