# Quickstart / Validation: Long, Naturally-Scrollable Session History

Proves the attached Claude session has local-terminal-like scrollback and natural mouse
scrolling. References the [tmux-session contract](./contracts/tmux-session.md) (C1–C8).

## Prerequisites

- A rebuilt `asdd/project:latest` image containing `/etc/tmux.conf` (this feature).
- A project with a running persistent session: `asdd serve <project>`.

## A. Static checks (no docker) — always run

```bash
make test            # includes tests/unit/test_tmux_config.py
```

Expected: the unit test passes, confirming `docker/files/asdd-tmux.conf` sets
`history-limit 50000` and `mouse on`, and that `docker/Dockerfile.project` copies it to
`/etc/tmux.conf`.

## B. Live server options (docker) — verifies C1, C2

With a session container running, read the live tmux server's options:

```bash
docker exec <asdd-project-container> tmux show-options -g history-limit
docker exec <asdd-project-container> tmux show-options -g mouse
```

Expected output:

```text
history-limit 50000
mouse on
```

(`tests/integration/test_scrollback_history.py` automates this and skips when docker is
unavailable.)

## C. Operator scroll experience — verifies C3, C4, C5

1. Attach: `asdd claude <project>` (or `asdd attach <project>`).
2. Generate several screens of output (e.g. ask Claude something long, or run a verbose
   command in `asdd open`).
3. Roll the mouse wheel **up** with no modifier key → the view scrolls back through
   history (C3).
4. Keep scrolling up past ~2000 lines of earlier output → it is still there, not truncated
   (SC-001).
5. Roll back down to the bottom (or wait for new output) → the view returns to the live
   session (C4).
6. Scroll hard against the top and bottom → scrolling stops cleanly; no error, session
   stays attached (C5).

## D. Copy, detach, consistency, posture — verifies C6, C7, C8

- **Copy-out (FR-006)**: select text with the mouse; to land it on the macOS clipboard,
  hold your terminal's bypass modifier (Option or Shift, terminal-dependent) while
  selecting. Selection remains usable.
- **Detach (C6)**: press `Ctrl-b d`. Then run `asdd ps` → the session is still up and
  mobile/web-visible; `claude` did not exit.
- **Consistency (C7)**: repeat section C after attaching via a different entry point
  (`asdd open` vs `asdd attach`). Behaviour is identical.
- **No new port (C8)**: `docker port <asdd-project-container>` shows no new inbound
  mapping introduced by this feature.

## Pass criteria

All of A–D behave as described, mapping to SC-001..SC-005 in the spec: ≥2000-line
read-back available, single-gesture modifier-free scroll, automatic return-to-live, and
zero regressions in detach / copy / mobile visibility / network posture.
