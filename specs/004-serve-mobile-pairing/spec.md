# Feature Specification: Reliable mobile-app pairing and reconnect for `asdd serve`

**Feature Branch**: `004-serve-mobile-pairing`

**Created**: 2026-06-13

**Status**: Draft

**Input**: User description: "Our serve function doesn't work — `asdd serve <project>` can be up and running yet the session is not visible in the Claude mobile app, while running `asdd claude <project>` and typing the `/remote-control` slash command inside the session reliably surfaces it on mobile. Serve must reliably pair the session with the operator's mobile app on startup, AND re-establish that pairing whenever connectivity is lost and later returns — that is the whole point of running serve unattended."

## Clarifications

### Session 2026-06-13

- Q: Who is responsible for re-establishing the mobile pairing when internet returns? → A: The in-container Claude process owns its outbound pairing connection and reconnects on its own. No container restart is triggered for transient pairing loss; the launchd babysitter only steps in on actual container/process exit.
- Q: Must the mobile-paired session be the same Claude instance the operator sees via `asdd claude <project>` and `asdd attach <project>`? → A: Yes. There is exactly one long-running Claude process per project. `asdd claude`, `asdd attach`, and the mobile-paired view all attach to that single process. `asdd claude` against a project with an active serve MUST NOT spawn a new Claude.
- Q: What should `asdd logout` do when serve sessions are running? → A: Tear them down first, then clear the credential store. Logout is a hard reset: no orphaned session is left holding a now-invalid pairing token, and the mobile app stops showing the sessions immediately rather than minutes later when the token would have expired.
- Q: Where does pairing status surface on the Mac? → A: Extend `asdd ps` with a "paired" column. One command the operator already knows; one glance covers every project. No new dedicated status command in this feature's scope.
- Q: What if the host has internet but Anthropic's pairing service itself is unreachable? → A: Treat it the same as "no internet": serve succeeds locally, pairing retries in the background indefinitely. No special distinction in error reporting between the two failure modes — the operator's expectation is "walk away and it'll pair when it can", and that holds regardless of which leg is broken.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Run `asdd serve`, see it on mobile, no manual step (Priority: P1) 🎯 MVP

The operator runs `asdd serve hello-world` on their Mac, walks away from the keyboard, picks up their phone, opens the Claude mobile app, and within a small bounded delay sees the `hello-world` session listed and openable. No additional command, no slash-command incantation, no host-side cookie copying. Pairing the session with the operator's account is part of what `asdd serve` does, not a separate step.

**Why this priority**: Today's behaviour is broken on this most basic case (the bug the operator reported on 2026-06-12). The interactive workaround — `asdd claude <id>` followed by typing `/remote-control` — is the very thing serve is supposed to obviate for unattended use. Until P1 is delivered, serve does not do what its name implies.

**Independent Test**: On a host with `asdd login` already completed, run `asdd serve hello-world`; within 30 seconds, open the Claude mobile app on the same operator's account and confirm the session appears in the list of remote-controllable sessions. Tap into it; confirm input from the phone reaches the session and output flows back.

**Acceptance Scenarios**:

1. **Given** the operator has a current `asdd login` and the host has internet, **When** they run `asdd serve hello-world` and wait up to 30 seconds, **Then** the `hello-world` session appears in the Claude mobile app for the same account, without any further command on the Mac.
2. **Given** the session has appeared in the mobile app, **When** the operator sends a prompt from the phone, **Then** Claude responds and the response is visible in both the mobile app and (when the operator re-attaches via `asdd attach`) the local tmux session.
3. **Given** the operator runs `asdd serve hello-world` then `asdd serve other-project`, **When** they open the mobile app, **Then** both sessions appear, distinguishable by project id, each independently controllable.

---

### User Story 2 — Pairing survives transient internet outages (Priority: P1)

The operator's home Wi-Fi drops for a few minutes, or they suspend/resume the Mac, or the laptop goes through a captive-portal reconnection. During the outage the session is unreachable from the phone (acceptable — the network is genuinely down). When connectivity returns, the session re-appears in the mobile app on its own — no `asdd serve` re-run, no slash-command incantation, no Mac-keyboard intervention.

**Why this priority**: The point of running serve unattended is to walk away and rely on it. An asdd serve that loses its mobile pairing on every Wi-Fi blip is no more useful than one that never paired in the first place; the operator would still need to be present at the Mac to recover. The operator named this auto-recovery as the explicit intention of the feature.

**Independent Test**: With a serve session running and visible in the mobile app, disable the Mac's network for at least 60 seconds. Confirm the mobile app shows the session as unreachable (or removes it from the list). Re-enable the network. Within 60 seconds of connectivity returning, confirm the session is back in the mobile app and accepts input again — without touching the Mac.

**Acceptance Scenarios**:

1. **Given** a serve session is paired with the mobile app, **When** the host loses internet for 60 seconds and then regains it, **Then** within 60 seconds of reconnection the session is visible and controllable from the mobile app again.
2. **Given** the host's Wi-Fi cycles through a captive portal (DNS resolves but HTTPS is blocked, then unblocks), **When** the portal is cleared, **Then** the session reconnects to the pairing service on its own.
3. **Given** the Mac is closed and reopened (suspend → resume), **When** the network and the container come back, **Then** within 60 seconds the session reappears in the mobile app.

---

### User Story 3 — Pairing survives container/Claude restarts (Priority: P2)

The container or the inner Claude process crashes. The launchd babysitter restarts it (existing spec 010 behaviour). The restarted session reappears in the mobile app the same way the original one did — no manual step, same session identity from the operator's point of view ("hello-world is back").

**Why this priority**: P2 because this scenario depends on a crash actually happening; the operator is not blocked on day one without it. But once US1 and US2 are delivered, the auto-restart machinery from spec 010 has to keep producing mobile-visible sessions or US1's "no manual step" guarantee silently degrades after the first crash.

**Independent Test**: With a serve session visible in the mobile app, stop the container (`docker stop`) to force a launchd-driven restart. Within 60 seconds the session is back in the mobile app under the same project id.

**Acceptance Scenarios**:

1. **Given** the launchd babysitter restarts a crashed container, **When** the new container's session is up, **Then** it appears in the mobile app within 60 seconds without operator action.
2. **Given** the session has been crash-restarted, **When** the operator opens it in the mobile app, **Then** the prior conversation context is available (existing `claude --continue` behaviour from spec 010).

---

### Edge Cases

- **Not logged in.** `asdd serve` already refuses when no Claude subscription credential is present. Surface the same error — pairing inherits from the same login.
- **`asdd logout` while serves are running.** `asdd logout` MUST first stop every running serve (uninstall their launchd babysitters, stop containers), then clear the credential store. The mobile app sees the sessions disappear within the normal launchd-stop window, not minutes later via a token expiry.
- **Logged in to a different account on mobile.** Out of scope: mobile shows whichever sessions belong to the account it is logged into. Pairing is per-account.
- **No internet at serve-start time.** The serve command should not silently fail to pair; it should either retry pairing in the background until internet is available (preferred) or refuse with a clear message. The operator should not have to remember to re-run anything once internet returns.
- **Stale pairing token in the credential store.** If the OAuth token in the shared credential store has expired between serve-start and pairing-attempt, the system handles the refresh the same way other commands do, and pairing completes.
- **Multiple Macs serving the same account.** Both Macs' sessions appear in the mobile app, distinguished by project id. Out of scope: deduplicating across hosts.
- **Mobile app force-closed and reopened.** Re-opening the app should show the current set of paired sessions; this is mobile-app behaviour, not asdd behaviour.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `asdd serve <project_id>`, run on a host with a valid Claude subscription login and internet, MUST cause that project's session to appear in the Claude mobile app (for the same account) within 30 seconds of `serve` returning, with no additional operator command.
- **FR-002**: The pairing MUST NOT require the operator to run any slash command (e.g. `/remote-control`) inside the session, nor any other manual step.
- **FR-003**: When the host loses internet connectivity while a paired serve session is running, and connectivity later returns, the session MUST re-appear in the mobile app within 60 seconds of the host having a working route to the pairing service, with no operator action.
- **FR-004**: When the launchd-supervised container is restarted (crash, OS reboot, manual stop+start), the restarted session MUST re-pair with the mobile app automatically, with the same project-id identity.
- **FR-005**: If `asdd serve` is run with no internet at the moment of invocation, or with internet but an unreachable pairing service, the command MUST succeed locally (the session starts), and pairing MUST be retried in the background indefinitely as connectivity becomes available. No distinction is drawn between "no internet" and "pairing service unreachable" — both surface as the same "reconnecting" state in `asdd ps`.
- **FR-006**: Pairing MUST use the same credential surface as the rest of asdd (the shared `_state/claude-auth/` store from spec 009 / spec 003) — no separate "mobile login" or second credential store.
- **FR-007**: Pairing MUST work without opening any inbound network port on the host or container (preserves the spec 010 invariant: outbound only, no listener).
- **FR-008**: The operator MUST be able to verify pairing status from the Mac without picking up the phone. `asdd ps` MUST surface pairing state — paired / unpaired / reconnecting — for every project alongside its running/stopped state.
- **FR-009**: When two or more projects are served concurrently, each session MUST be paired and visible in the mobile app independently; loss of pairing for one MUST NOT take down the other.
- **FR-010**: The diagnosis the user reported — that `asdd claude` + `/remote-control` works but `asdd serve` does not — MUST be addressed at the root: the cause of the divergence is identified, and `asdd serve` is changed so the same registration the slash command performs happens automatically on serve start.
- **FR-011**: There MUST be exactly one long-running Claude process per project. `asdd claude <project>`, `asdd attach <project>`, and the mobile-paired view MUST all attach to that single process — observing the same conversation history, the same in-flight prompt, and the same output stream. `asdd claude <project>` against a project with an active serve MUST NOT spawn a new Claude instance; it MUST join the existing one.
- **FR-012**: Reconnect after transient network loss (FR-003) MUST be driven by the in-container Claude process re-establishing its outbound pairing connection. Transient pairing loss MUST NOT trigger a container restart (which would create a new Claude instance and break FR-011). Container restart by the launchd babysitter is reserved for actual container/process exit (FR-004).

### Key Entities

- **Paired serve session**: an `asdd serve` invocation that has successfully registered with the operator's mobile-app pairing service. Identified by project id, scoped to the operator's account, has a current/expired/reconnecting status observable from both the Mac (FR-008) and the mobile app.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a host with current login and internet, 100% of fresh `asdd serve <id>` invocations result in the session appearing in the mobile app within 30 seconds, with no further command from the operator.
- **SC-002**: After a network outage of any duration that ends with connectivity restored, the session re-appears in the mobile app within 60 seconds of route restoration, on at least 19 of 20 trials (≥95%).
- **SC-003**: After a launchd-driven container restart, the post-restart session is mobile-visible within 60 seconds on at least 19 of 20 trials.
- **SC-004**: The operator can determine from the Mac whether a serve session is currently paired with the mobile app, without opening the mobile app, in a single command.
- **SC-005**: Zero operator-visible regressions in the existing serve behaviours: `asdd attach`, `asdd stop`, `asdd serve --supervise`, restart-count tracking, the workspace-trust pre-acceptance, and the per-project state isolation from spec 003 all behave identically.
- **SC-006**: Documentation in `USER_GUIDE.md` describes the new behaviour in operator-facing terms, including how to check pairing status and what to do when pairing has stalled.

## Assumptions

- The Claude Code CLI inside the container is a current-enough version to support whatever the mobile pairing mechanism actually is at implementation time. If `claude --remote-control` (CLI flag) and `/remote-control` (slash command) are different mechanisms — which is what the user's observation suggests — the implementation will identify which one truly drives mobile pairing and use it from serve. If they are the same and the difference is a TTY-attached-vs-not bug, the implementation will work around that.
- The "pairing service" Claude Code uses to surface CLI sessions on mobile is owned by Anthropic and reached over outbound HTTPS from the host/container. asdd does not host it.
- The operator's mobile app is signed in to the same Anthropic account whose subscription login is in `_state/claude-auth/`. (If they differ, mobile won't see the session — that's an account-pairing issue, out of scope.)
- The spec 010 supervisor architecture (launchd KeepAlive, no inbound port, host-side babysitter) is unchanged. This feature changes only what runs inside the persistent container so that mobile pairing is established and auto-recovered.
- The spec 003 isolation invariant — credential surface shared, per-project state isolated — continues to hold. Pairing uses the shared credentials, not per-project state.
- "Within 60 seconds of connectivity returning" is timed from the moment a TCP/TLS connection to the pairing service would actually succeed (post-DHCP, post-DNS, post-captive-portal), not from the moment the Wi-Fi icon shows bars.
