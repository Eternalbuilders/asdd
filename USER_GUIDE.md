# ASDD — Install & First-Project Guide

ASDD runs Claude Code inside a per-project Docker container on your Mac and
manages those containers for you. Instead of pointing `claude` straight at your
laptop's filesystem, each project gets an isolated container with only its own
workspace mounted — so an agent can edit, run, and experiment freely without
any path to the rest of your machine.

Three reasons to use it:

- **A safe Claude development environment.** Claude works inside a container
  that can only see one project's files. A bad command, a runaway script, or an
  over-eager refactor can't touch your home directory, your other projects, or
  your system — `ls /` inside the container doesn't even show them. You get the
  upside of letting Claude act autonomously without putting your Mac at risk.
- **Always-on remote sessions.** Start a persistent Claude session that keeps
  running on the Mac, auto-restarts if it crashes or after a reboot, and shows
  up in the Claude app on your phone and at claude.ai. Kick something off at
  your desk and keep steering it from your phone later.
- **Scheduled, unattended jobs.** Write a task as a markdown file and have
  Claude run it later — overnight, on a timer, whenever — with the result
  written back into the project. Nobody has to be at the keyboard.

Everything authenticates with **your Claude subscription** — one login, reused
everywhere. A metered API key is an optional override, not a requirement.

This guide installs the CLI, builds the project container image, and walks
through your first project end to end.

---

## 1. What's in the repo

You install ASDD by cloning the repo (§3). The parts that matter at runtime:

```
asdd/                          ← the CLI Python package
└── contracts/                 ← JSON schemas asdd reads at import time
docker/
├── Dockerfile.project         ← project-container image
└── files/
    ├── asdd-run-job.sh        ← in-container job runner (dispatch)
    └── asdd-session.sh        ← in-container persistent-session entrypoint
project_skeleton/              ← scaffold copied into every new project
pyproject.toml                 ← installs the `asdd` console script
specs/                         ← symlink to a dev-only spec store; dangles on a
                               ← Mac clone, which is fine — runtime never reads it
```

The clone **is** your ASDD source tree on this machine. Don't delete or move it
after install — the CLI computes paths relative to where this tree lives (the
Dockerfile from `<repo>/docker/`, the scaffold from `<repo>/project_skeleton/`,
the schemas from `<repo>/asdd/contracts/`). A good home is `~/asdd/`.

Python dependencies installed by `pip`/`pipx`: `PyYAML`, `jsonschema`, `click`.
That's it.

---

## 2. Host prerequisites

Everything below is installed with Homebrew. Run the steps in order on the
target Mac before any `asdd` command.

### 2.1 Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

If you already have it, skip this. (See https://brew.sh.)

### 2.2 A Docker engine (Colima)

`asdd` shells out to `docker build` / `docker run`, so you need a running Docker
engine. [OrbStack](https://orbstack.dev/) is the smoothest option on macOS but
its licence is free **for personal use only**, so this guide uses **Colima**,
which is open source and unrestricted. (Docker Desktop also works and carries
its own licensing terms.)

```bash
brew install colima docker docker-buildx

# Register the Homebrew buildx plugin so `docker build` (buildkit) works.
mkdir -p ~/.docker/cli-plugins
ln -sfn "$(brew --prefix)/opt/docker-buildx/bin/docker-buildx" ~/.docker/cli-plugins/docker-buildx

# Start the VM. Defaults are 2 CPU / 2 GB; bump it for comfortable
# image builds + Claude Code sessions. `colima start` also points the
# `docker` CLI at this VM automatically.
colima start --cpu 4 --memory 8

# Smoke-test the daemon (prints "Hello from Docker!", then exits cleanly).
docker run --rm hello-world
```

> **Colima file-sharing caveat.** Unlike OrbStack, Colima only mounts your
> **home directory** (and `/tmp/colima`) into its VM by default. `asdd`
> bind-mounts `$ASDD_HOME/projects/<id>` into containers, so **`ASDD_HOME` must
> live under your home directory** (the `~/asdd` default below is fine). Point
> it somewhere outside `$HOME` and container mounts silently come up empty.

Colima survives reboots only if you start it again (or `brew services start
colima`). Stop the VM with `colima stop` when you don't need it.

### 2.3 Python 3.12 and pipx

```bash
brew install python@3.12
brew install pipx && pipx ensurepath
```

### 2.4 git

`asdd new` runs `git` on the host (both `git clone` for `--from-remote` and
`git init` for an empty project):

```bash
brew install git   # or use the git from Xcode Command Line Tools
```

You do **not** need `uv`, `sops`, `age`, `node`, or Claude Code on the host —
those are all pre-installed inside the project image. You log in to Claude with
`asdd login --fresh` (§4), which runs the login *inside* a container, so
nothing about Claude has to exist on the host first.

### Do I need an Anthropic API key?

**No — not for normal use.** Every mode (interactive, dispatch, persistent)
authenticates with your Claude subscription via a one-time `asdd login`, and the
stored session refreshes itself automatically, including for unattended jobs.
The persistent / mobile session in fact *requires* the subscription login —
Claude Code's Remote Control only works with a claude.ai subscription, not an
API key.

A metered `ANTHROPIC_API_KEY` is an **opt-in override** for one situation: when
you want a specific `asdd dispatch` run billed to API usage instead of your
subscription — for example to keep a client's token costs separate, or to avoid
spending your subscription's rate limit on a large batch job. You pass
`--api-key` on that single run (§8), and the subscription store is then not
mounted for it. If you don't have that need, ignore the API key entirely.

---

## 3. Install the ASDD CLI and initialise `ASDD_HOME`

```bash
# 1. Clone the repo to a permanent home. This directory IS your install —
#    don't move or delete it afterwards (the CLI resolves the Dockerfile and
#    template paths relative to it).
git clone https://github.com/Eternalbuilders/asdd.git ~/asdd
cd ~/asdd

# 2. Install in editable mode. Editable is REQUIRED — see above.
pipx install --editable . --python python3.12
# or, without pipx:
#   python3.12 -m venv .venv && source .venv/bin/activate && pip install -e .

# 3. Verify
asdd --help
```

Update later with a plain `git -C ~/asdd pull` (the editable install picks up
the new code automatically — no reinstall needed).

You should see the `asdd` subcommands: `init`, `new`, `list`, `open`, `close`,
`ps`, `dispatch`, `serve`, `attach`, `stop`, `session`, `login`, `logout`,
`whoami`, `secrets …`.

### Pick where projects live

Set `ASDD_HOME` to the directory where projects, registry, and templates will
land. Default is `~/Code/asdd`. Keep it **under your home directory** (see the
Colima caveat in §2.2).

```bash
# In ~/.zshrc (persisted across shells)
export ASDD_HOME=$HOME/asdd-home
```

Open a new shell so the variable takes effect, then initialise it:

```bash
asdd init
```

`asdd init` is idempotent and creates:

```
$ASDD_HOME/
├── _state/           ← projects.yml registry, audit.log
├── _archive/         ← archived projects (empty on day one)
├── projects/         ← per-project workspaces (one dir per project)
└── _templates/       ← copied from the repo's project_skeleton/
```

---

## 4. Log in to Claude (subscription)

asdd authenticates to Claude using **your Claude subscription**, established
once and reused by every mode (interactive `open`, autonomous `dispatch`, and
the persistent session). Credentials live in an asdd-owned store at
`$ASDD_HOME/_state/claude-auth/` — never inside a project, never committed. Do
this once, before creating or running anything.

```bash
asdd login           # seeds from your existing Mac ~/.claude login if present
asdd whoami          # shows status (logged in? as whom? expiry?) — no network call
```

If you have never used Claude Code on this Mac:

```bash
asdd login --fresh   # drops you into a container running `claude`; complete
                     # the login (open the printed URL, paste the code), exit.
```

Log out (e.g. handing off the machine) with `asdd logout`. After logout, every
mode refuses Claude work until you log in again. The stored session refreshes
itself automatically — including for unattended jobs — so a one-time login
keeps working without re-authentication.

`ANTHROPIC_API_KEY` is not required for routine work; it is an opt-in override
(see §8) for billing a specific run to metered usage instead.

---

## 5. Create a project

A project is a workspace under `$ASDD_HOME/projects/<id>/` plus a registry
entry. `asdd new` lays the spec-driven-development scaffolding (`.specify/`,
`inbox/`, `jobs/`, `results/`, `schedule/`, `_state/`, `specs/`, a starter
`constitution.md`) into it. You can start empty or from an existing repo.

### From scratch

```bash
asdd new hello-world \
  --name "Hello World" \
  --description "First test project"
```

This `git init`s a fresh repo on `main` and commits the scaffolding.

### From an existing GitHub repo

`asdd new <id> --from-remote <git-url>` clones the repo into
`$ASDD_HOME/projects/<id>/` and lays the same scaffolding on top — on a
**separate branch** called `asdd/bootstrap`, so your project's `main` stays
untouched.

```bash
# Example: pull in github.com/octocat/Hello-World as a new ASDD project.
asdd new hello-world \
  --from-remote https://github.com/octocat/Hello-World.git \
  --name "Hello World" \
  --description "First test project"
```

The repo's existing files are preserved on `main`; the scaffolding sits on
`asdd/bootstrap`. Switch between them with normal git.

Verify either way:

```bash
asdd list
# ID                       STATE        NAME
# hello-world              active       Hello World

ls $ASDD_HOME/projects/hello-world
# .git  .specify  README  _state  inbox  jobs  results  schedule  specs
```

> **First-time build note**: the next step (`asdd serve`, `asdd open`, or `asdd
> dispatch`) triggers a one-time `docker build` of `asdd/project:latest`, which
> takes ~30–60 seconds. The CLI streams the build output so it isn't silent.

---

## 6. Start a persistent, always-on session (`serve`)

A persistent session is ONE long-lived Claude conversation that stays running
on the Mac: it survives closing your terminal, auto-restarts if it crashes or
after a reboot, resumes its conversation, **and is reachable from the Claude
mobile app / claude.ai**. It runs on your subscription (spec 009) — no API key.

```bash
asdd serve hello-world          # start a supervised persistent session
asdd attach hello-world         # re-attach your terminal (tmux); Ctrl-b d detaches, session keeps running
asdd session status hello-world # running? restart_count? supervised?
asdd stop hello-world           # the ONLY way it stays down (also disables the supervisor)
```

Continuing on your phone: because the session runs `claude --remote-control`,
it registers with Anthropic over an **outbound** connection and appears in the
**session list in the Claude mobile app and at claude.ai automatically** — no
inbound port is opened on the Mac. Open the Claude app on your phone, pick the
session (named after the project), and you're in the *same* conversation that's
running on your Mac: read what it's done, send the next instruction, approve a
step. Whatever you do on the phone shows up when you re-attach locally with
`asdd attach`, and vice versa — it's one shared session, not a copy. So you can
start work at your desk, walk away, and keep driving it from the train.

The container's actual code, files, and tools never leave your Mac; Anthropic's
backend only relays your messages. To grab the join URL/QR directly, attach
locally (`asdd attach <id>`) — it's shown at the top of the session.

How it works under the hood:
- The container's main process is a `tmux` session running one interactive
  `claude --remote-control`. tmux keeps that single session alive with no
  client attached, so it stays mobile-visible AND is locally re-attachable.
  `asdd attach` / `asdd open` run `tmux attach`, dropping you into the *same*
  conversation (mobile and your terminal share it — they stay in sync, but
  don't type in both at once).
- A per-project launchd agent (`~/Library/LaunchAgents/com.asdd.session.<id>.plist`)
  runs `asdd serve <id> --supervise` as a foreground babysitter. When the
  container exits (crash, OOM, daemon restart), the babysitter exits too and
  launchd's `KeepAlive` relaunches it — which restarts the container and
  resumes the conversation (`--continue`). `RunAtLoad` brings it back on
  login/reboot. The supervisor is host-side only and opens **no** inbound port.
- While a session is up, `asdd dispatch <id>` runs the job **inside** the
  warm container — one container per project, reused.

Stopping is authoritative: `asdd stop` disables the launchd agent first, then
removes the container, so it does not come back until you `serve` again.

---

## 7. Interactive Claude session inside the container (`open`)

```bash
asdd open hello-world
```

You land at a bash prompt **inside** the container, at `/asdd_home`. The prompt
looks like:

```
asdd@<container-id>:/asdd_home$
```

What's mounted from your Mac:
- the project workspace at `/asdd_home` (read/write)
- your asdd subscription credentials (from `$ASDD_HOME/_state/claude-auth/`)
  onto the container user's `~/.claude.json` and `~/.claude`, so Claude Code is
  already logged in from your `asdd login` (§4)

Everything else on the Mac is invisible — `ls /` won't show your home dir or
other projects.

Start an interactive Claude session:

```
asdd@…:/asdd_home$ claude
> /speckit-specify add a /healthz endpoint
```

Spec-kit slash commands work out of the box because `.specify/integration.json`
was wired in during `asdd new`.

**To leave**, just `exit` the shell. The container stops automatically — no
processes remain on the host (`docker ps` is empty).

If you killed your terminal or lost the SSH connection, clean up manually:

```bash
asdd close hello-world
```

(`open` is for an ad-hoc, one-off shell. For a session you want to keep alive
and drive from your phone, use `asdd serve` — §6.)

---

## 8. Define and run an autonomous job (`dispatch`)

A "job" is **just a markdown file** whose body is piped to `claude --print`
inside the container. No frontmatter is required.

Constraints:
1. The file must exist.
2. The path must be **under** that project's workspace (i.e. somewhere inside
   `$ASDD_HOME/projects/<id>/`), because that's the only path the container
   can see.

Convention is to drop job-notes into `inbox/`:

```bash
mkdir -p $ASDD_HOME/projects/hello-world/inbox

cat > $ASDD_HOME/projects/hello-world/inbox/audit.md <<'EOF'
# job: dependency audit

Read package.json, list every dependency, and flag any that have
not had a release in the last 24 months. Output a short markdown table.
EOF
```

Run it now:

```bash
# Production: runs on your Claude subscription, using the login you
# established with `asdd login` (§4). No API key needed.
asdd dispatch hello-world \
  $ASDD_HOME/projects/hello-world/inbox/audit.md
```

What happens:
1. The project's container starts in **autonomous mode** (workspace mount
   plus your asdd-owned subscription credential store).
2. `asdd-run-job` reads the markdown file and pipes its body to
   `claude --print`, authenticated on your subscription.
3. Claude's stdout is written to
   `$ASDD_HOME/projects/hello-world/results/audit.result.md`.
4. The container stops. `docker ps` is empty again.

The CLI prints the result path to stdout. If you have not logged in, the
dispatch fails fast and tells you to run `asdd login`.

### Bill a single run to an API key instead

```bash
ANTHROPIC_API_KEY=sk-ant-… asdd dispatch hello-world \
  $ASDD_HOME/projects/hello-world/inbox/audit.md --api-key
# This run uses metered billing; the subscription store is NOT mounted.
```

### Test path (no LLM calls / no API key / no login)

```bash
export ASDD_JOB_STUB_OUTPUT="canned response for testing"
asdd dispatch hello-world $ASDD_HOME/projects/hello-world/inbox/audit.md
# audit.result.md contains "canned response for testing"
```

Useful for verifying the dispatch pipeline end-to-end without spending tokens.

---

## 9. Schedule a job for later

The ASDD CLI itself has **no built-in scheduler** — `asdd dispatch` is a
fire-now primitive. To run something later, use macOS's standard `at`(1)
daemon, which is purpose-built for one-off scheduled commands.

### One-time setup on a fresh Mac

`atrun` ships disabled on modern macOS. Enable it once:

```bash
sudo launchctl load -F /System/Library/LaunchDaemons/com.apple.atrun.plist
```

This survives reboots.

### Schedule a single run

This runs on your Claude subscription — no API key. The stored login refreshes
itself, so a job scheduled now still authenticates when it fires hours later,
with nobody at the keyboard. The only thing the non-interactive `at` shell
needs spelled out is `ASDD_HOME` (your `.zshrc` isn't loaded — see caveats):

```bash
echo "export ASDD_HOME=$ASDD_HOME; \
      $(which asdd) dispatch hello-world \
        $ASDD_HOME/projects/hello-world/inbox/audit.md \
        > $HOME/asdd-dispatch.log 2>&1" \
  | at 21:00
```

(If you wanted *this* run billed to a metered API key instead of your
subscription, add `--api-key` to the `dispatch` command and `export
ANTHROPIC_API_KEY=sk-ant-…;` ahead of it. Not needed for normal use — see §2.)

Other time forms `at` accepts:
- `at now + 30 minutes`
- `at 9am tomorrow`
- `at 14:00 saturday`

Inspect and manage:

```bash
atq           # list queued jobs
atrm <jobid>  # remove a queued job
```

### Caveats to know

- `at` runs in a **non-interactive shell** — your `.zshrc` exports aren't
  loaded. Put any env vars (`ASDD_HOME`, and `ANTHROPIC_API_KEY` only if you're
  using the API-key override) inline in the command you pipe to `at`, or
  `source` your `~/.zshrc` first.
- Use absolute paths. The example above uses `$(which asdd)` and the full
  `$ASDD_HOME` path for that reason.
- `at` does **not** wake a sleeping Mac. If the Mac is asleep at the fire
  time, the job runs whenever the Mac next wakes. If you need wake-from-sleep,
  use `launchd` with `StartCalendarInterval` + `WakeFromSleep=true` instead
  (heavier setup; not covered here).
- Redirect stdout/stderr to a file (the example uses `$HOME/asdd-dispatch.log`).
  Otherwise `at` mails the output via local Postfix, which is rarely useful.

---

## 10. Useful inspection commands

```bash
asdd list                 # registered projects
asdd ps                   # currently-running project containers
asdd close <id>           # force-stop a project's container

ls $ASDD_HOME/projects/<id>/results/   # past job outputs
docker images asdd/project             # image storage on the host
docker logs asdd-project-<id>          # if a container is misbehaving
```

---

## 11. Per-project secrets (optional)

If a project needs API keys other than `ANTHROPIC_API_KEY`, ASDD ships a
SOPS + age based secret store. Setup is one-time:

```bash
# Generate an age keypair (do this once per Mac)
age-keygen -o ~/.config/age/keys.txt
# Add the recipient to ~/.zshrc:
export SOPS_AGE_KEY_FILE=$HOME/.config/age/keys.txt
export SOPS_AGE_RECIPIENTS=age1…   # the recipient line from keys.txt
```

Then:

```bash
asdd secrets add hello-world DATABASE_URL --value "postgres://…"
asdd secrets list hello-world
asdd secrets remove hello-world DATABASE_URL
```

Secrets are decrypted on the host at dispatch/open time and passed into the
container as environment variables (never written to disk inside).

You don't need this for the smoke test in §5–§9.

---

## 12. Uninstall / clean slate

```bash
# Stop everything and remove the registry/projects:
asdd ps | awk 'NR>1 {print $1}' | xargs -n1 asdd close 2>/dev/null
rm -rf "$ASDD_HOME"

# Drop the image:
docker rmi asdd/project:latest

# Remove the CLI:
pipx uninstall asdd
# (or `pip uninstall asdd` if you used a venv)

# Optionally remove the cloned repo:
rm -rf ~/asdd

# And stop / remove the Docker engine if you no longer need it:
colima stop        # or `colima delete` to remove the VM entirely
```

---

## Quick reference card

```
asdd init                                    initialise $ASDD_HOME
asdd login [--fresh]                         establish Claude subscription auth
asdd whoami                                  show auth status (no network call)
asdd logout                                  clear stored subscription auth
asdd new <id>                                create empty project
asdd new <id> --from-remote <url>            create project from existing repo
asdd list                                    show projects
asdd serve <id>                              start a persistent supervised session
asdd attach <id>                             attach to a persistent session (detach leaves it up)
asdd session status <id>                     show persistent-session status
asdd stop <id>                               stop session + disable supervisor (durable)
asdd open <id>                               interactive shell in container
asdd close <id>                              force-stop container
asdd ps                                      list running containers
asdd dispatch <id> <job.md>                  run one job now (autonomous, subscription)
asdd dispatch <id> <job.md> --api-key        run one job billed to ANTHROPIC_API_KEY
asdd secrets {add,remove,list} <id> [args]   manage per-project secrets

echo '<cmd>' | at <time>                     fire <cmd> once at <time>
atq        atrm <n>                          inspect / cancel scheduled jobs
```

---

## A note on automode (bypassing permission prompts)

The whole reason Claude runs inside a per-project container is so you can let it
work in **automode** — Claude Code's `--dangerously-skip-permissions` ("YOLO")
mode, where it edits files and runs commands without stopping to ask for
approval on each action. On a bare laptop that flag is genuinely dangerous; here
it isn't, because the container can only see one project's workspace. A wrong
command, a runaway script, or an over-eager refactor stays trapped inside the
container — it can't reach your home directory, your other projects, or the
host. The container is the blast radius, and `asdd` keeps it small. **That
isolation is the point: the image exists precisely so automode is safe to run.**

Today:

- **Interactive (`asdd open`)** — start the session in automode yourself:
  ```bash
  asdd@…:/asdd_home$ claude --dangerously-skip-permissions
  ```
- **Autonomous (`asdd dispatch`)** and **persistent (`asdd serve`)** — the
  in-container entrypoints (`asdd-run-job.sh`, `asdd-session.sh`) invoke `claude`
  *without* that flag, by design: automode stays an explicit opt-in rather than
  baked-in default behavior. If you want a hands-off dispatch or serve run, edit
  those entrypoint scripts yourself to add `--dangerously-skip-permissions`.
