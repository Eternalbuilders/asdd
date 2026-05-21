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

## 1. What's in this bundle

```
asdd-bundle/
├── USER_GUIDE.md                  ← this file
├── README.md
├── pyproject.toml                 ← installs the `asdd` console script
├── asdd/                          ← the CLI Python package
│   └── contracts/                 ← JSON schemas asdd reads at import time
├── docker/
│   ├── Dockerfile.project         ← project-container image
│   └── files/
│       ├── asdd-run-job.sh        ← in-container job runner (dispatch)
│       └── asdd-session.sh        ← in-container persistent-session entrypoint
└── project_skeleton/              ← scaffold copied into every new project
```

The unpacked directory **is** your ASDD source tree on this machine. Don't
delete or move it after install — the CLI computes paths relative to where this
tree lives (the Dockerfile from `<bundle>/docker/`, the scaffold from
`<bundle>/project_skeleton/`, the schemas from `<bundle>/asdd/contracts/`). A
good home is `~/asdd/`.

Python dependencies installed by `pip`/`pipx`: `PyYAML`, `jsonschema`, `click`.
That's it.

---

## 2. Host prerequisites

Install these on the target Mac, in this order, before running any `asdd`
command:

1. **Docker or OrbStack** — the CLI shells out to `docker build` / `docker run`,
   and your sessions run as containers. [OrbStack](https://orbstack.dev/) is
   recommended on macOS (lighter and faster); Docker Desktop also works.
2. **Homebrew** — the simplest way to install the rest. See https://brew.sh if
   you don't already have it.
3. **Python 3.12+** — `asdd` requires it: `brew install python@3.12`.
4. **pipx** — cleanest way to install a console script in isolation:
   `brew install pipx && pipx ensurepath`.
5. **git** — `asdd new --from-remote` clones repos with it: `brew install git`
   (the Xcode Command Line Tools also provide it).

You do **not** need `uv`, `sops`, `age`, `node`, or Claude Code on the host —
those are all pre-installed inside the project image. You log in to Claude with
`asdd login --fresh` (§6a), which runs the login *inside* a container, so
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

## 3. Install the ASDD CLI

```bash
# 1. Pick a permanent home for the bundle and unpack into it.
mkdir -p ~/asdd
tar -xzf asdd-bundle.tar.gz -C ~/asdd --strip-components=1
cd ~/asdd

# 2. Install in editable mode. Editable is REQUIRED — the CLI resolves the
#    Dockerfile and template paths relative to this directory.
pipx install --editable . --python python3.12
# or, without pipx:
#   python3.12 -m venv .venv && source .venv/bin/activate && pip install -e .

# 3. Verify
asdd --help
```

You should see the `asdd` subcommands: `init`, `new`, `list`, `pause`,
`resume`, `archive`, `open`, `close`, `ps`, `dispatch`, `secrets …`.

### Pick where projects live

Set `ASDD_HOME` to the directory where projects, registry, and templates
will land. Default is `~/Code/asdd`.

```bash
# In ~/.zshrc (persisted across shells)
export ASDD_HOME=$HOME/AI-Hub/asdd
```

Open a new shell so the variable takes effect.

---

## 4. Initialise `ASDD_HOME`

```bash
asdd init
```

This is idempotent and creates:

```
$ASDD_HOME/
├── _state/           ← projects.yml registry, audit.log
├── _archive/         ← archived projects (empty on day one)
├── projects/         ← per-project workspaces (one dir per project)
└── _templates/       ← copied from the bundle's controlvault-skeleton/_templates/
```

---

## 5. Create a project that pulls in an existing GitHub repo

`asdd new <id> --from-remote <git-url>` clones the repo into
`$ASDD_HOME/projects/<id>/` and lays the spec-driven-development scaffolding
(`.specify/`, `inbox/`, `jobs/`, `results/`, `schedule/`, `_state/`,
`specs/`, a starter `constitution.md`) on top — on a **separate branch**
called `asdd/bootstrap`, so your project's `main` stays untouched.

```bash
# Example: pull in github.com/octocat/Hello-World as a new ASDD project
# called "hello-world".
asdd new hello-world \
  --from-remote https://github.com/octocat/Hello-World.git \
  --name "Hello World" \
  --description "First test project"
```

Verify:

```bash
asdd list
# ID                       STATE        NAME
# hello-world              active       Hello World

ls $ASDD_HOME/projects/hello-world
# .git  .specify  README  _state  inbox  jobs  results  schedule  specs
```

The repo's existing files are preserved on `main`; the scaffolding sits on
`asdd/bootstrap`. Switch between them with normal git.

> **First-time build note**: the next step (`asdd open` or `asdd dispatch`)
> will trigger a one-time `docker build` of `asdd/project:latest`,
> which takes ~30–60 seconds. The CLI streams the build output so it isn't
> silent.

---

## 6. Interactive Claude session inside the container

```bash
asdd open hello-world
```

You land at a bash prompt **inside** the container, at `/asdd_home`. The
prompt looks like:

```
asdd@<container-id>:/asdd_home$
```

Three things are bind-mounted from your Mac:
- the project workspace at `/asdd_home` (read/write)
- your `~/.claude/` directory (so Claude Code is already logged in)
- your `~/.claude.json` file (same reason)

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

---

## 6a. First-time login (Claude subscription)

asdd authenticates to Claude using **your Claude subscription**, established
once and reused by every mode (interactive `open`, autonomous `dispatch`,
and the persistent session). Credentials live in an asdd-owned store at
`$ASDD_HOME/_state/claude-auth/` — never inside a project, never committed.

```bash
asdd login           # seeds from your existing Mac ~/.claude login if present
asdd whoami          # shows status (logged in? as whom? expiry?) — no network call
```

If you have never used Claude Code on this Mac:

```bash
asdd login --fresh   # drops you into a container running `claude`; complete
                     # the login (open the printed URL, paste the code), exit.
```

Log out (e.g. handing off the machine) with `asdd logout`. After logout,
every mode refuses Claude work until you log in again. The stored session
refreshes itself automatically — including for unattended jobs — so a
one-time login keeps working without re-authentication.

`ANTHROPIC_API_KEY` is no longer required for routine work; it is an opt-in
override (see §8) for billing a specific run to metered usage instead.

---

## 7. Define a job for autonomous execution

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

---

## 8. Run a job now (one-shot dispatch)

```bash
# Production: runs on your Claude subscription, using the login you
# established with `asdd login` (see §6a). No API key needed.
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

## 8c. Keep a session always-on (workflow 3: persistent / remote-control)

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

Stopping is authoritative: `asdd stop` disables the launchd agent first,
then removes the container, so it does not come back until you `serve` again.

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

# Optionally remove the bundle source tree:
rm -rf ~/asdd
```

---

## Quick reference card

```
asdd init                                    initialise $ASDD_HOME
asdd login [--fresh]                         establish Claude subscription auth
asdd whoami                                  show auth status (no network call)
asdd logout                                  clear stored subscription auth
asdd new <id> --from-remote <url>            create project from existing repo
asdd new <id>                                create empty project
asdd list                                    show projects
asdd open <id>                               interactive shell in container
asdd close <id>                              force-stop container
asdd ps                                      list running containers
asdd dispatch <id> <job.md>                  run one job now (autonomous, subscription)
asdd dispatch <id> <job.md> --api-key        run one job billed to ANTHROPIC_API_KEY
asdd serve <id>                              start a persistent supervised session
asdd attach <id>                             attach to a persistent session (detach leaves it up)
asdd session status <id>                     show persistent-session status
asdd stop <id>                               stop session + disable supervisor (durable)
asdd secrets {add,remove,list} <id> [args]   manage per-project secrets

echo '<cmd>' | at <time>                     fire <cmd> once at <time>
atq        atrm <n>                          inspect / cancel scheduled jobs
```
