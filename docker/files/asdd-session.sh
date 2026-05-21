#!/usr/bin/env bash
# asdd-session — persistent supervised Claude session (spec 010).
#
# This is the main process (PID 1) of a persistent-mode container started by
# `asdd serve <id>`. It runs ONE long-lived interactive Claude session inside
# a tmux session named `asdd`, with Remote Control enabled so the operator can
# drive it from the Claude mobile app / claude.ai (outbound-only; no inbound
# port is opened — constitution IV).
#
# Why tmux: it keeps the single interactive `claude` alive with no client
# attached, so the session stays mobile-visible AND is locally re-attachable
# via `docker exec -it <c> tmux attach -t asdd` (that is what `asdd attach` /
# `asdd open` do). Detaching the tmux client (Ctrl-b d) does not stop claude.
#
# Lifecycle: this script blocks until the tmux session ends (claude exits).
# When it returns, the container exits, and the host-side launchd babysitter
# (`asdd serve <id> --supervise`) relaunches it — that is the auto-restart.
#
# Two roles in one file: the default (outer) role sets up tmux and blocks; the
# `--inner` role is what tmux actually runs in the pane — it resumes the prior
# conversation if there is one, else starts fresh. Splitting it this way keeps
# the conversation-resume logic in a real script (not a brittle tmux arg) and
# lets the outer role stay a dumb supervisor loop.

set -euo pipefail

SESSION="asdd"
NAME="${ASDD_PROJECT_ID:-asdd}"

# --- inner role: the actual session, run by tmux inside the pane -------------
if [ "${1:-}" = "--inner" ]; then
    if [ -n "${ASDD_SESSION_STUB:-}" ]; then
        # Test/CI: hold the container up without a live LLM so the
        # restart/persistence primitive can be exercised.
        exec sleep infinity
    fi

    # Resume the prior conversation when one exists. `claude --continue` is
    # keyed on the working directory and exits immediately when there is no
    # conversation to resume — so we can't tell up front whether history
    # exists for THIS workspace (a global file check disagrees with claude and
    # caused a restart loop). Instead: try --continue; if it returns in under a
    # few seconds it had nothing to resume, so fall through to a fresh session.
    start=$(date +%s)
    claude --continue --remote-control --name "$NAME" || true
    elapsed=$(( $(date +%s) - start ))
    if [ "$elapsed" -lt 5 ]; then
        claude --remote-control --name "$NAME" || true
    fi
    exit 0
fi

# --- outer role: supervise the tmux session (PID 1) --------------------------
tmux new-session -d -s "$SESSION" "$0 --inner"

# Block PID 1 until the session ends so the launchd babysitter sees the
# container exit and relaunches it.
while tmux has-session -t "$SESSION" 2>/dev/null; do
    sleep 5
done
