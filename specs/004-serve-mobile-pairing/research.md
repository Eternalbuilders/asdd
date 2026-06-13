# Research — 004-serve-mobile-pairing

Resolves the Technical Context open question from `plan.md` and locks four concrete decisions. Findings are grounded in `claude --help` output and direct inspection of Claude Code 2.1.175's on-disk state in this devcontainer.

## R1. The pairing-status truth surface

**Decision**: Detect pairing status by reading the running session's state file at `~/.claude/sessions/<pid>.json` inside the container and checking the `bridgeSessionId` field. Non-empty → paired. Absent/empty → not paired.

**Evidence**: this devcontainer's own running Claude writes:

```json
{
  "pid": 13,
  "sessionId": "778fad15-…",
  "cwd": "/asdd_home",
  "kind": "interactive",
  "entrypoint": "cli",
  "name": "TD",
  "status": "busy",
  "bridgeSessionId": "session_019rvN…"
}
```

The `bridgeSessionId` is the identifier claude.ai assigns when remote-control pairing is established. It is exactly the file-based signal asdd needs for `asdd ps`'s new "paired" column (FR-008): no network probe, no Anthropic-API call, just a `cat` on a JSON file inside the container.

**Rationale**:

- It's authoritative — the file IS what Claude writes when the bridge is up.
- It survives serve restarts cleanly: when Claude exits, the file is gone or stale; when the new Claude pairs, it rewrites the file. So a "paired" reading is current-process-truth, not a cached stale.
- Matches constitution Principle II ("plain files where humans read state"). An operator can `docker exec <c> cat ~/.claude/sessions/*.json | jq .bridgeSessionId` to debug.
- No new dependency, no extra credential, no new state file invented by asdd.

**Alternatives considered**:

- **Network probe to the bridge service**. Rejected: adds an outbound call from the host's `asdd ps` (not from inside the container), introduces latency on every `ps`, leaks ps-time info to Anthropic, and "online" ≠ "this particular session is paired".
- **Parse Claude's stdout/log for a pairing line**. Rejected: brittle, version-coupled, requires PID 1 to capture and persist Claude's output. We have a JSON file already.
- **Add an asdd-owned marker file written by `asdd-session.sh` after pairing succeeds**. Rejected: redundant with what Claude already records; asdd would have to detect pairing from outside Claude anyway to write the marker, so the dependency just inverts.

## R2. Pairing mechanism — diagnosis and minimal intervention

**Decision (working hypothesis, to confirm in implementation)**: the divergence between `asdd-session.sh`'s `claude --remote-control` (no mobile-visible) and the operator's `asdd claude → /remote-control` (mobile-visible) is most likely one of three root causes, listed in order of probability:

1. **`--remote-control` requires interactive `stdin` to complete its first-time-per-session handshake**, and `tmux new-session -d` (detached) leaves the pane's claude with no live client reading from it. The slash-command path works because by then a terminal client is attached and reading.
2. **Outbound HTTPS to the bridge service is failing only for the serve container**, due to a different env (no `TERM`, no `SHLVL`, container-only DNS path). Less likely — the same container, same network namespace, works after attach.
3. **`--remote-control` initiates pairing but the bridge-registration confirm message is dropped to a non-tty fd**, which silently fails the handshake. Cousin of (1).

**Minimal intervention plan** (apply in order; stop at the first that works in implementation):

A. Attach an idle tmux client at session startup so claude has a "live" terminal from the moment it runs. Implemented in `asdd-session.sh` outer role as `tmux attach -t asdd -d 2>/dev/null &` immediately after `tmux new-session -d`, with a `disown` so the attached client survives the outer script's lifecycle. The idle client holds an open pty; claude sees a normal interactive terminal; `--remote-control` completes its handshake. Cost: ~10MB extra memory for the idle tmux client.

B. If (A) doesn't fix it, drop the `--remote-control` CLI flag and instead start plain `claude` then auto-type the `/remote-control` slash command via `tmux send-keys` after a short settle delay. Emulates the exact path that empirically works for the operator. More fragile (timing, future Claude version compat) but guaranteed-equivalent to what they observe working.

C. If neither works, fall back to running claude with `script(1)` to give it a forced pty independent of tmux, and have tmux attach to script's pty. Heavier, last-resort.

**Rationale**: the cheapest hypothesis to test is also the cheapest to fix. Spec 010's outer role IS the right architecture — keeping tmux as the session holder preserves `asdd attach` and FR-011's single-process guarantee. We are only adding "always have a client attached", not changing topology.

**Alternatives considered**:

- **Drop tmux; run claude as PID 1 directly with `docker run -it`**. Rejected: serve is launchd-driven and unattended; you cannot `docker run -it` from a launchd agent without a terminal. The whole point of tmux here is to provide a persistent pty inside an unattended container.
- **Replace claude with the Claude SDK and implement pairing in Python**. Rejected: out of scope, introduces a maintained dependency on an evolving SDK, and we don't control bridge-protocol changes.
- **Open an inbound TCP socket for tmux-attach from the host**. Rejected: violates the spec 010 "no inbound port" invariant.

## R3. Reconnect after transient network loss

**Decision**: Rely on Claude Code's own bridge-reconnect behaviour inside the long-running process. asdd does NOT add a watchdog, does NOT probe pairing status periodically, and does NOT restart the container on transient pairing loss. The only asdd intervention is to surface the current state in `asdd ps` so the operator can verify recovery has happened.

**Rationale**: from the spec clarification — the in-container Claude owns its outbound pairing; transient pairing loss is a Claude-internal event. The `bridgeSessionId` field will reappear in the session JSON when Claude re-pairs. If Claude Code does NOT reconnect on its own — discovered during implementation — that is a Claude Code bug to report upstream; asdd will not work around it with a periodic restart, because that violates FR-011 (single long-running process per project, same conversation across reconnects).

**Mitigation if Claude does not auto-reconnect**: ship anyway with the limitation documented in USER_GUIDE.md (FR-003 unmet, operator runs `asdd stop && asdd serve` to recover), open an upstream issue with Anthropic. Defer the workaround to a future spec.

**Alternatives considered**:

- **Watchdog that restarts the container when pairing has been absent for >N seconds**. Rejected: violates FR-011/FR-012 — restart creates a new Claude PID with a new conversation context.
- **Watchdog that sends `/remote-control` again via `tmux send-keys` when bridgeSessionId disappears**. Rejected unless empirically required: adds keystroke injection complexity. Reconsider only if R2 intervention A or B requires it for steady state.

## R4. `cmd_logout` teardown order

**Decision**: `asdd logout` runs the equivalent of `asdd stop` against every project whose registry row is in state `active` and has a running persistent container (per `is_persistent_running`), in any order — they're independent. Only after all teardown returns does it call `auth.clear`. If a teardown fails, log it, continue to the next project, and at the end either (a) refuse to clear if any teardown failed, or (b) clear anyway and warn — see decision row.

**Sub-decision**: on a teardown failure, **refuse to clear and exit non-zero**. The operator should resolve the stuck container before their account is logged out — otherwise the orphaned container holds an invalid bridge token and pollutes the mobile-app session list for whoever logs in next.

**Rationale**: Logout is rare and operator-initiated. The cost of "stop one project at a time" is a few seconds; the cost of leaving an orphan running with valid credentials at logout time is a real-world security hole (next operator account inherits a paired session they didn't authorise).

**Alternatives considered**:

- **Clear credentials first, then attempt teardown**. Rejected: serves try to refresh tokens against the now-empty store and either crash loudly or quietly start showing auth errors in the mobile app. The user sees a sequence of "session is having problems" notifications instead of a clean disappearance.
- **Force-kill containers and clear regardless**. Rejected: a container that refuses `docker stop` cleanly usually has work in flight (long-running claude prompt). Force-kill mid-prompt is operator-hostile.

## Open questions

None for plan exit. R2 has a confirm-in-implementation step (the experiments A/B/C are ordered); that is normal Phase-2/3 work, not a Phase-0 blocker.
