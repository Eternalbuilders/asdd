# Contract — `asdd-session.sh` (PID 1 of the serve container)

## Scope

Changes the outer-role startup so the inner `claude --remote-control` runs with a tmux client already attached (R2 intervention A). No change to the inner role's contract (still resumes via `--continue` then falls through to fresh).

## Outer-role contract (before → after)

### Before

```bash
SESSION="asdd"
NAME="${ASDD_PROJECT_ID:-asdd}"
tmux new-session -d -s "$SESSION" "$0 --inner"
while tmux has-session -t "$SESSION" 2>/dev/null; do
    sleep 5
done
```

### After

```bash
SESSION="asdd"
NAME="${ASDD_PROJECT_ID:-asdd}"
tmux new-session -d -s "$SESSION" "$0 --inner"

# Spec 004 R2: keep an idle client attached so claude --remote-control
# sees a live terminal at startup and completes its bridge handshake.
# `-d` detaches any other client (idempotent across crash-restarts).
# Backgrounded + disowned so PID 1 (this script) stays the supervisor.
tmux attach -t "$SESSION" -d </dev/null >/dev/null 2>&1 &
disown

while tmux has-session -t "$SESSION" 2>/dev/null; do
    sleep 5
done
```

## Behavioural contract

- The script MUST keep being PID 1; the backgrounded idle client MUST NOT inherit PID 1's role.
- The idle client MUST survive across operator `asdd attach` / `asdd claude` sessions — those operator-initiated attaches detach the idle one with `tmux attach -d`, but the idle client's parent shell loop notices the detach and reattaches (alternative: don't reattach — see implementation note below).
- The idle client MUST NOT consume stdin from anywhere reachable by the inner claude (closed stdin, redirected to /dev/null).
- The outer loop's `while tmux has-session` semantics MUST be unchanged; container exits only when the tmux session ends (claude exits).

## Implementation note — operator attach interaction

When an operator runs `asdd attach` (which does `docker exec -it <c> tmux attach -t asdd`), the operator's client and the idle client are two tmux clients attached to the same session. tmux supports multiple clients per session; both see the same content. When the operator detaches (Ctrl-b d), the idle client is still attached. When the operator's terminal closes without detaching, tmux drops their client and the idle one remains. Net effect: the bridge handshake's "live terminal" guarantee survives all operator behaviour, with no special handling.

If empirical testing shows that two-clients-attached causes display issues (rare; tmux is designed for this), the alternative is to start the idle client only until first operator attach, then exit the idle. This is a fallback, not the planned approach.

## Fallback intervention paths

If R2 intervention A (this contract) does not make `bridgeSessionId` appear in the session JSON within ~10 seconds of serve startup:

**Intervention B** — replace the inner role's launch with a plain `claude` (no `--remote-control`), then have the outer role auto-type the slash command after a 5-second settle delay:

```bash
tmux send-keys -t "$SESSION" "/remote-control" Enter
```

**Intervention C** — wrap claude in `script(1)` to force a pty independent of tmux:

```bash
script -qfc "claude --continue --remote-control --name \"$NAME\"" /dev/null
```

Each is a single-line change to `asdd-session.sh`. Implementation phase decides which to apply based on the first that produces `bridgeSessionId` reliably.

## Unit test contract (bash-level)

| Test | Expected |
|---|---|
| Outer role runs `tmux new-session -d` exactly once before any `tmux attach` | ✓ |
| Outer role backgrounds the idle attach with `&` and `disown` | ✓ |
| Outer role's idle attach has stdin redirected to /dev/null | ✓ |
| Inner role's startup chain (`--continue` then fallback) unchanged | ✓ (existing tests) |
| With `ASDD_SESSION_STUB=1`, the inner role still execs `sleep infinity` | ✓ (existing test) |
