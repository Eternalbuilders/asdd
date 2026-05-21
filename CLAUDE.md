# CLAUDE.md — orientation for Claude working on the asdd repo

This file is for Claude sessions opened inside this repo. It is the
sole agent-instruction surface for sessions working in
`/workspace/asdd-repo/` — do **not** read or inherit from
`/workspace/CLAUDE.md` or `/workspace/AGENTS.MD`. Anything load-bearing
from those files has been folded in below.

If you're a human reader, `README.md` is the right starting point; it
points onward to `USER_GUIDE.md` for install + operator workflows and
to `TRANSFER.md` for the extraction story and outstanding follow-ups.

## What this repo is

The asdd CLI and its per-project container manager. See `README.md` for
the user-facing summary. The three operating modes — `asdd open`
(interactive shells), `asdd dispatch` (autonomous markdown job runs), and
`asdd serve` (a persistent, launchd-supervised, auto-restarting session) —
are documented in `USER_GUIDE.md`.

Code layout is conventional Python: package at `asdd/`, Dockerfiles at
`docker/`, scaffold at `project_skeleton/`, tests at `tests/`.

## Where this repo lives — dev vs deploy

This distinction is non-obvious and easy to get wrong:

- **Dev (here)**: `/workspace/asdd-repo/` inside this Linux devcontainer.
  All editing, testing, and `/speckit-*` slash commands happen here.
- **Deploy**: `make bundle` produces `asdd-bundle.tar.gz` (~35 KB),
  unpacked on a Mac at `~/asdd/` (or similar) and installed via
  `pipx install --editable .`. The Mac runs `asdd` against `$ASDD_HOME`
  projects. **The Mac doesn't run this dev workflow** — it's purely a
  deploy target.

Do not assume you can develop from the Mac side.

For ad-hoc CLI runs in-container without installing:
```bash
PYTHONPATH=. python3.12 -m asdd.bootstrap --help
```
Everything else (`make test`, `make lint`, `make bundle`, `make clean`)
is just the Makefile.

## Specs and the vault symlink

The `specs/` directory is a **symlink to the ControlVault Obsidian vault**
at `/vaults/ControlVault/Specs/asdd/`. The master spec docs live in the
vault, not in git. The symlink:

- Resolves transparently in this container — `ls specs/`, `cat
  specs/007-asdd-architecture/spec.md`, and `/speckit-*` slash commands
  all work as if the specs were inside the repo.
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
| Tests pass before commit | `make test` | 102 unit tests; integration tests skip cleanly when docker isn't available. |
| Subscription auth is the default for all modes | `asdd/auth.py`, `asdd/project_container.py:auth_mounts` | Spec 009: every mode mounts the asdd-owned store at `$ASDD_HOME/_state/claude-auth/`; `ANTHROPIC_API_KEY` is opt-in (`dispatch --api-key`), not the default. Supersedes spec 008 FR-009 for Claude creds. |
| Credential store never leaves `$ASDD_HOME` | `.gitignore`, `asdd/auth.py` | Holds live OAuth tokens; excluded from project workspaces, archives, and `make bundle`; `0700/0600`. |
| Persistent-session supervisor is host-side launchd only; no inbound port | `asdd/supervisor.py` | Spec 010: container kept alive by Docker `--restart unless-stopped` + a launchd agent (`RunAtLoad`); nothing in-container calls launchd; "remote-control" is local attach, never an inbound listener. |

## Working with the user

The user is Marius (marius@froisland.no). The following conventions
apply across their projects; honour them here too.

**Communication**
- Be terse. State results, then stop. Don't trail with summaries.
- No emojis in files or messages unless asked.
- **Stepwise walkthroughs**: when guiding through multi-step setup or
  testing on the Mac, present **one step at a time**, wait for the
  result, then move on. Don't dump a full checklist.
- **Mac command clarity**: when asking the user to run a command on
  their Mac, lead with one short labelled sentence naming the command
  and the output to paste back. Example: "Run this on your Mac and
  paste the final summary line: `python3 -m pytest ...`"

**Git / commits**
- Short summary line. Body explains *why*, not what (the diff shows what).
- Co-Authored-By trailer with the model name.
- One logical change per commit. Prefer incremental edits over rewrites.
- **Never** force-push, delete git history, or skip hooks (`--no-verify`).

**Safety**
- **Never** use `sudo`, install global packages on the user's host
  without asking, or access secrets / credentials in unexpected places.

## Don't edit the upstream copy

The source `vaultcontrol` monorepo at `/workspace/` still has its own
copy of `asdd/` and the related specs. From this repo's perspective
that copy is **frozen**. If you find yourself wanting to make a change
in `/workspace/asdd/`, that's the wrong tree — make it here in
`/workspace/asdd-repo/asdd/` instead.

The full extraction story and outstanding follow-ups live in
`TRANSFER.md`.

## Pointers

- `README.md` — user-facing install + workflow summary
- `USER_GUIDE.md` — full operator path (projects, dispatch, scheduling)
- `TRANSFER.md` — extraction story, what got renamed, open follow-ups
