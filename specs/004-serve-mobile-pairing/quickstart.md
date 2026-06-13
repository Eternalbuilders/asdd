# Quickstart — 004-serve-mobile-pairing validation

Operator-facing runbook to verify the fix end-to-end. Sections 1–4 run on the Mac deploy target with a real Docker and a real iPhone/Android. Section 5 is a Mac-only logout-cleanliness check.

## Prerequisites

- `asdd` installed from this branch (`git pull && pipx install --editable .`)
- Docker available on `PATH`
- A current `asdd login` (subscription credential present)
- An iPhone or Android phone with the Claude mobile app signed in to the **same** Anthropic account
- Two scratch projects to play with: `pair-a` and `pair-b`

## 1. Fresh serve appears in the mobile app (FR-001, SC-001)

```bash
asdd project create pair-a
asdd serve pair-a

# Watch the new column in ps
asdd ps
# Expected within ~10 seconds:
# PROJECT  MODE        STATE   PAIRED  CONTAINER
# pair-a   persistent  active  paired  asdd-project-pair-a
```

On the phone, open the Claude app. Within 30 seconds the `pair-a` session should appear in the Remote Control session list. Tap it; type a prompt; confirm a response.

**Diagnostic** (only if `paired` doesn't show within 30s):

```bash
docker exec asdd-project-pair-a cat ~/.claude/sessions/*.json | python3 -m json.tool | grep -iE "bridgeSessionId|kind|cwd|updatedAt"
```

If `bridgeSessionId` is absent → R2 intervention A didn't take; try B or C. If present but `asdd ps` shows `unpaired` → the host-side reader is wrong; the file is the truth.

## 2. Same session in `asdd claude` (FR-011)

```bash
asdd claude pair-a
```

You should land **inside the same conversation** that the mobile app is showing — not a fresh Claude. Type a prompt locally; confirm it appears on the phone too. Detach with Ctrl-b d. `asdd ps` should still show `paired`.

## 3. Pairing survives a brief network outage (FR-003, SC-002)

```bash
# Cut the Mac's network for 90 seconds (Wi-Fi off, or pull the cable).
# The mobile app will show pair-a as unreachable or remove it from the list.

# Restore network.
# Within 60 seconds of route restoration:
asdd ps          # PAIRED transitions: reconnecting → paired
# Mobile app:     pair-a re-appears in the session list.
```

Repeat the cycle a few times. SC-002 requires ≥95% (19/20) of trials to recover within 60 seconds.

## 4. Pairing survives a container restart (FR-004, SC-003)

```bash
docker stop asdd-project-pair-a
# launchd babysitter relaunches the container automatically within ~5 seconds.

asdd ps          # within 60s: PAIRED = paired again
```

On the phone, the session should reappear under the same `pair-a` name. The conversation history should be intact (`claude --continue` resume from spec 010).

## 5. `asdd logout` cleans everything (Q2, FR-006)

```bash
asdd serve pair-b      # second project for the multi-stop check

# Phone shows both pair-a and pair-b. Now:
asdd logout
# Expected behaviour:
# - both containers stopped + removed
# - both launchd babysitters uninstalled
# - shared credential surface cleared
# Phone: pair-a and pair-b vanish from the session list within ~30 seconds.

# Any project: starting now requires fresh login.
asdd serve pair-a      # Expected: refuses, names asdd login
```

**Failure-mode check**: make one container unstoppable (suspend it from outside docker, or rely on a flaky one), then run `asdd logout`. Confirm it refuses to clear the store and names the failing project — matches `contracts/asdd-logout.md`.

## 6. Two projects served concurrently (FR-009)

Already exercised in section 5 (two serves running side-by-side). Spot-check:

```bash
asdd serve pair-a
asdd serve pair-b
asdd ps   # both rows show paired within 30s
```

Cut the network briefly. Confirm both go to `reconnecting` then back to `paired` — neither lags far behind the other (the recoveries are independent).

## Done When

- Sections 1–6 execute as documented on the Mac.
- `make test` is green (unit + the new docker-gated `test_serve_pairing.py` either runs or skips cleanly).
- `asdd ps` shows the new `PAIRED` column for every running serve.
- `asdd logout` honors the refuse-on-teardown-failure contract.
