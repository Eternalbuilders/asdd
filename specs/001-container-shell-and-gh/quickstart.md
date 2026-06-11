# Quickstart: validating feature 001 end-to-end

**Feature**: 001-container-shell-and-gh
**Audience**: the operator (or anyone validating the PR) once `/speckit-implement` has landed.

This runbook proves the four user stories work end-to-end against a real container. It assumes:

- A registered project (`my-app` is used as the example) exists.
- The asdd CLI is installed editable (`pipx install --editable .` in the repo root, or `PYTHONPATH=. python3.12 -m asdd.bootstrap` for ad-hoc runs).
- Docker is available on the host.

## Prerequisites

```bash
# Make sure the new image is built — every workflow below depends on it.
asdd open my-app   # First run builds the image; we use it immediately below.
```

(If `asdd open` is what you're testing, the first invocation also doubles as a build, so this step is free.)

## US1 — `asdd open` lands at a bash shell, no Claude

```bash
$ asdd open my-app
(my-app) asdd@<container-id>:/asdd_home$ echo $SHELL
/bin/bash
(my-app) asdd@<container-id>:/asdd_home$ pgrep -fl claude
# (no output — Claude is not running)
(my-app) asdd@<container-id>:/asdd_home$ exit
$ docker ps --filter "label=asdd.mode=interactive" --format "{{.Names}}" | grep my-app
# (no output — container is stopped)
```

Verify:

- The first line includes `(my-app)` — that's User Story 3 working.
- `pgrep -fl claude` finds no Claude — that's User Story 1.
- After `exit`, no running container — FR-002.

## US2 — `asdd claude` starts Claude

```bash
$ asdd claude my-app
# Claude TUI opens. Have a one-line conversation, then /exit.
$ docker ps --filter "label=asdd.mode=interactive" --format "{{.Names}}" | grep my-app
# (no output — container is stopped)
```

Verify:

- Claude opens directly (no detour through a shell).
- After exiting Claude, the container is stopped — FR-005.

## US2.b — Persistent-session re-attach

```bash
$ asdd serve my-app   # in one terminal, starts the persistent session.
$ asdd claude my-app  # in another terminal, should attach to the existing tmux'd Claude.
# Detach with Ctrl-b d. The session keeps running.
$ asdd ps
# (my-app is still listed as running.)
$ asdd stop my-app    # tear down at the end.
```

Verify:

- `asdd claude my-app` re-attached rather than failing or starting a second Claude — FR-006.
- After detaching, `asdd ps` still shows my-app running.

## US2.c — `asdd open` while a persistent session runs

```bash
$ asdd serve my-app
$ asdd open my-app
error: A persistent session is running for project 'my-app'.
       Use `asdd attach` to join it, or `asdd claude` to start a Claude inside it.
$ asdd stop my-app
```

Verify:

- `asdd open` refuses with the named error rather than silently joining the session — FR-003 + R5.

## US3 — Shell prompt shows project name

```bash
# Two terminals, two projects.
# Terminal A:
$ asdd open project-alpha
(project-alpha) asdd@…$ echo "I am in alpha"

# Terminal B:
$ asdd open project-beta
(project-beta) asdd@…$ echo "I am in beta"
```

Verify:

- A colleague glancing at either terminal can tell which project that shell is for from the prompt alone — SC-003.
- On the host (a third terminal), the prompt does NOT have the prefix — FR-010.

## US3.b — Sub-shell preserves the prefix

```bash
(my-app) asdd@…$ bash
(my-app) asdd@…$ # sub-shell still has the prefix because the env var is container-level.
(my-app) asdd@…$ exit
(my-app) asdd@…$
```

Verify FR-008's sub-shell case.

## US4 — `gh` works on first try

```bash
$ asdd open my-app
(my-app) asdd@…$ gh --version
gh version 2.94.0 (2026-XX-XX)
https://github.com/cli/cli/releases/tag/v2.94.0
(my-app) asdd@…$ gh auth login
# Device-code flow. Complete in a browser.
(my-app) asdd@…$ gh auth status
github.com
  ✓ Logged in to github.com account warigeiko
(my-app) asdd@…$ exit
```

Verify:

- `gh --version` exits 0 without "command not found" — SC-004.
- `gh auth login` completes the device-code flow without any prerequisites — US4 acceptance scenario 2.

## US4.b — `gh` works on both architectures

```bash
# On an amd64 host:
$ docker run --rm asdd/project:latest gh --version
gh version 2.94.0 ...

# On an arm64 host (e.g., Apple Silicon):
$ docker run --rm asdd/project:latest gh --version
gh version 2.94.0 ...
```

Verify FR-012.

## Regression — `asdd dispatch` and `asdd serve` unchanged

```bash
# Drop a job note into the inbox, then:
$ asdd dispatch my-app inbox/some-job.md
# Result lands under results/some-job.result.md as today.

$ asdd serve my-app
# Persistent session boots, supervised by launchd as today.
$ asdd attach my-app
# Re-attaches to the running session.
$ asdd stop my-app
```

Verify these flows behave identically to before feature 001 — FR-014.

## Cleanup

```bash
asdd close my-app           # Stop any stray interactive container.
asdd stop  my-app           # Stop any persistent session.
docker image prune --filter "label=asdd"  # Optional: drop the built image.
```

## What this quickstart does NOT cover

- The auth-store provisioning flow (covered by spec 009's quickstart).
- The first-time `asdd init` / `asdd new` flow (covered by `USER_GUIDE.md`).
- Building the image from scratch on a host without Docker (out of scope).

## Failure modes & recovery

| Symptom | Likely cause | Fix |
|---|---|---|
| `asdd open` lands in Claude | You're on an old binary; the new `cmd_open` is not deployed. | Re-install: `pipx install --editable . --force` in the repo root. |
| Prompt is missing the `(project)` prefix | You're on an old image. | `asdd close my-app && docker rmi asdd/project:latest && asdd open my-app` to rebuild. |
| `gh: command not found` | Same as above — old image. | Rebuild as above. |
| `asdd claude` returns "auth not configured" | The subscription auth store is empty. | Run `asdd login` (spec 009). |
| `asdd open` refuses with "persistent session running" | Expected. | Use `asdd attach my-app` to join the session. |
