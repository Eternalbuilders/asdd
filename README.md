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

## Quick install — fresh Mac, fresh repo

```bash
# 1. Host prerequisites
brew install python@3.12 pipx git
pipx ensurepath
npm install -g @anthropic-ai/claude-code
claude login                                  # populates ~/.claude/
# Plus a container runtime: OrbStack (recommended) or Docker Desktop

# 2. Get the source
git clone https://github.com/<owner>/asdd ~/Code/asdd
cd ~/Code/asdd

# 3. Install the CLI (editable — keep the repo in place after this)
pipx install --editable . --python python3.12

# 4. Pick where projects live
echo 'export ASDD_HOME=$HOME/AI-Hub/asdd' >> ~/.zshrc
exec zsh

# 5. Initialise and smoke-test
asdd init
asdd new smoke --description "smoke test"
asdd open smoke
# inside the container:  ls /asdd_home ; exit
```

If `asdd open smoke` lands you at a shell prompt and `exit` cleans up
quietly, you're good.

For the post-install path — projects, dispatch, scheduling — see
`USER_GUIDE.md`.

---

## What's in this repo

```
asdd/                  # the CLI Python package
├── bootstrap.py       # Click command tree
├── project_container.py
├── _schemas.py        # reads asdd/contracts/ at import time
└── contracts/         # schemas asdd validates against (NOT spec docs)
docker/
├── Dockerfile.project # the per-project image
└── files/asdd-run-job.sh
project_skeleton/      # scaffold copied into every new project
                       # (.specify/ is added by `uvx specify init`)
specs -> /Users/marius/Vaults/ControlVault/Specs/asdd/
                       # symlink to master specs (in your vault)
tests/                 # unit + integration
pyproject.toml         # installs the `asdd` console script
README.md  USER_GUIDE.md  TRANSFER.md  Makefile
```

The `specs/` directory is a symlink to the master spec location in your
Obsidian vault, so `/speckit-*` slash commands work directly against
spec docs that are always visible in Obsidian and never affected by
worktrees. See `TRANSFER.md` for details.

## Makefile targets

```
make install     # pipx install --editable .
make test        # pytest
make lint        # ruff check
make bundle      # build asdd-bundle.tar.gz for transport to another Mac
make clean       # remove build artifacts
```

`make bundle` produces a self-contained tarball suitable for installing
on a different Mac without `git clone` (useful if the target doesn't
have GitHub access). See `USER_GUIDE.md` §3 for the tarball install
path.

## Host requirements

| Tool | Why |
| --- | --- |
| Container runtime — OrbStack or Docker Desktop | Builds & runs project images |
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

## Where things live at runtime

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
