# ASDD — Agentic Spec-Driven Development

A CLI + per-project container manager. Each project gets an isolated
Linux container with git, Claude Code, `uv`, and the spec-kit slash
commands preinstalled. Open a project's environment with one command;
the host filesystem outside the project is invisible from inside.

Two modes:
- **Interactive** — `asdd open <id>` drops you into a bash shell inside
  the project's container with your Claude Code subscription auth
  bind-mounted in. Type `claude`, use `/speckit-*` slash commands.
- **Autonomous** — `asdd dispatch <id> <job.md>` runs one markdown
  "job-note" through `claude --print` inside the container, writes the
  result, and stops. No subscription auth involved — uses
  `ANTHROPIC_API_KEY` instead, so scheduled work can't drain your
  subscription quota.

---

## Where this repo lives, and how to work with it

Two environments, by design:

| | Dev (in this devcontainer) | Deploy (Mac host) |
| --- | --- | --- |
| Location | `/workspace/asdd-repo/` | `~/asdd/` (after unpacking the bundle) or wherever you choose |
| Edit code? | Yes | No (deploy artifact) |
| Run tests? | Yes (`make test`) | No |
| Build bundle? | Yes (`make bundle`) | No |
| `/speckit-*` slash commands? | Yes — write through to vault | No |
| `specs/` symlink resolves? | Yes (`/vaults/ControlVault/Specs/asdd/`) | No (dangles — harmless, runtime doesn't use it) |
| Run `asdd` CLI? | Optional — primarily for testing | **Yes — this is the production runtime** |

Master specs live in the ControlVault Obsidian vault. `specs/` in the
repo is a symlink to that vault location, so `/speckit-*` slash commands
inside this repo write transparently to the vault and the specs are
always visible in Obsidian. See `TRANSFER.md` for the full design.

## Dev workflow (in this devcontainer)

```bash
cd /workspace/asdd-repo
make test                       # run pytest (skips docker tests if no daemon)
make lint                       # ruff
make bundle                     # produce asdd-bundle.tar.gz for deploy
ls specs/                       # see specs in the vault via the symlink
```

`/speckit-*` slash commands run inside Claude Code while you're in this
repo will write to `specs/` → which is the vault, so the spec docs are
immediately visible in Obsidian.

## Deploy to a Mac

```bash
# 1. In the devcontainer: build the bundle
cd /workspace/asdd-repo
make bundle
# → asdd-bundle.tar.gz

# 2. Carry the tarball to the target Mac (scp, AirDrop, etc.)

# 3. On the Mac: unpack and install
mkdir -p ~/asdd
tar -xzf asdd-bundle.tar.gz -C ~/asdd --strip-components=1
cd ~/asdd
pipx install --editable . --python python3.12
asdd --help
```

For the full Mac install path including host prerequisites
(Docker/OrbStack, Python 3.12, Claude Code login, etc.), see
`USER_GUIDE.md` §1–§5.

For day-to-day operator usage (creating projects from GitHub repos,
running jobs, scheduling) see `USER_GUIDE.md` §5–§9.

---

## What's in this repo

```
asdd/                  # the CLI Python package
├── bootstrap.py       # Click command tree
├── project_container.py
├── _schemas.py        # reads asdd/contracts/ at import time
└── contracts/         # JSON schemas asdd validates against (in-package data)
docker/
├── Dockerfile.project # the per-project image (asdd/project:latest)
└── files/asdd-run-job.sh
project_skeleton/      # scaffold copied into every new project
                       # (.specify/ is added by `uvx specify init`)
specs -> /vaults/ControlVault/Specs/asdd/
                       # symlink to master specs (in your vault)
tests/                 # unit + integration
pyproject.toml         # name=asdd, deps: PyYAML, jsonschema, click
README.md  USER_GUIDE.md  TRANSFER.md  Makefile
```

## Makefile targets

```
make help        # this list
make install     # pipx install --editable . (host CLI install — for Mac use)
make test        # pytest
make lint        # ruff check
make bundle      # build asdd-bundle.tar.gz (excludes specs/ symlink)
make clean       # remove build artifacts
```

## Host requirements (for deploy to Mac)

| Tool | Why |
| --- | --- |
| OrbStack or Docker Desktop | Builds & runs project images |
| Python 3.12+ | `pyproject.toml` requires it |
| `pipx` (recommended) | Cleanest way to install the CLI |
| `git` | `asdd new --from-remote` clones GitHub repos |
| Claude Code (`@anthropic-ai/claude-code`) | Logged in once on the host; auth bind-mounted into containers |

You do **not** need `uv`, `sops`, `age`, or `node` on the host — those
are inside the project image.

## Dependencies (Python)

Three deps:
- `PyYAML` — registry I/O
- `jsonschema` — registry + audit validation
- `click` — CLI

## Where things live at runtime (post-install)

```
$ASDD_HOME/
├── _state/projects.yml   # the registry
├── _state/audit.log
├── _templates/           # copied from project_skeleton/ at `asdd init`
├── projects/<id>/        # per-project workspace, bind-mounted into the container at /asdd_home
└── _archive/             # archived projects
```

## License

Proprietary.
