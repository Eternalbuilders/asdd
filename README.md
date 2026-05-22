# ASDD — Agentic Spec-Driven Development

A CLI and per-project container manager for running Claude Code safely. Each
project gets an isolated Linux container with git, Claude Code, `uv`, and the
spec-kit slash commands preinstalled — open a project's environment with one
command, and the host filesystem outside the project stays invisible from
inside.

Authentication is your **Claude subscription**, established once with
`asdd login` and reused by every mode (no API key required). Credentials live
in an asdd-owned store under `$ASDD_HOME/_state/claude-auth/`.

Three modes:
- **Interactive** — `asdd open <id>` drops you into a bash shell inside the
  project's container with your subscription auth mounted in. Type `claude`,
  use `/speckit-*` slash commands.
- **Autonomous** — `asdd dispatch <id> <job.md>` runs one markdown "job-note"
  through `claude --print` inside the container, writes the result, and stops.
  Pass `--api-key` to bill a specific run to `ANTHROPIC_API_KEY` instead.
- **Persistent** — `asdd serve <id>` keeps a supervised Claude session running:
  it survives detach, auto-restarts on crash/reboot, resumes its conversation,
  and is reachable from the Claude mobile app / claude.ai. `asdd attach` /
  `asdd stop` connect and shut it down. No inbound network port is opened.

## Install and usage

See **[USER_GUIDE.md](USER_GUIDE.md)** for the complete path: host
prerequisites, installing the CLI, building the container image, creating
projects, running and scheduling jobs, and the persistent/mobile session.

The rest of this README is for working on asdd itself.

---

## Repository layout

```
asdd/                     # the CLI Python package
├── bootstrap.py          # Click command tree (the `asdd` entry point)
├── project_container.py  # docker run/exec/ps lifecycle
├── auth.py               # subscription credential store
├── supervisor.py         # launchd agent for persistent sessions
├── _schemas.py           # reads asdd/contracts/ at import time
└── contracts/            # JSON schemas asdd validates against (in-package data)
docker/
├── Dockerfile.project    # the per-project image (asdd/project:latest)
└── files/
    ├── asdd-run-job.sh    # in-container dispatch runner
    └── asdd-session.sh    # in-container persistent-session entrypoint
project_skeleton/         # scaffold copied into every new project
specs/                    # symlink to the master spec docs (kept outside git;
                          # dangles in a fresh clone — runtime never reads it)
tests/                    # unit + integration (integration gated on docker)
pyproject.toml            # name=asdd; deps: PyYAML, jsonschema, click
```

## Development

asdd is developed inside a Linux container (a Python 3.12 devcontainer); the
Mac is only a deploy target, never a dev environment.

```bash
make test     # pytest — unit always; integration skips without a docker daemon
make lint     # ruff check
make bundle   # build asdd-bundle.tar.gz for deployment
make clean    # remove build artifacts
```

For an ad-hoc CLI run in-container without installing:

```bash
PYTHONPATH=. python3.12 -m asdd.bootstrap --help
```

The `specs/` symlink points at a master spec store that lives outside git, so
`/speckit-*` slash commands run from this repo write spec docs through to that
store. It is excluded from `make bundle` and dangles harmlessly in any clone
that doesn't have that store mounted; the runtime never reads `specs/` (schemas
ship in `asdd/contracts/`).

## Build and deploy

`make bundle` produces `asdd-bundle.tar.gz` (~50 KB) — the CLI plus only the
files it needs at runtime. Unpack it on a Mac and `pipx install --editable .`
(see [USER_GUIDE.md](USER_GUIDE.md) for the full install). The bundle is the
only deploy artifact; the Mac does not run this dev workflow.

## Dependencies

Three runtime deps, kept deliberately lean:
- `PyYAML` — registry I/O
- `jsonschema` — registry + audit validation
- `click` — CLI

`uv`, `sops`, `age`, and `node` are not host requirements — they're inside the
project image.

## Runtime layout (post-install)

```
$ASDD_HOME/
├── _state/projects.yml      # the registry
├── _state/audit.log
├── _state/claude-auth/      # subscription credential store (git-ignored)
├── _templates/              # copied from project_skeleton/ at `asdd init`
├── projects/<id>/           # per-project workspace, mounted at /asdd_home
└── _archive/                # archived projects
```

## License

Proprietary.
