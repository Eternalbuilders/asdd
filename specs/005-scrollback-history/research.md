# Phase 0 Research: Long, Naturally-Scrollable Session History

## R1 — Why scrollback is short and scrolling is awkward today

**Finding**: The interactive session is not a direct terminal→Claude connection. Per
`docker/files/asdd-session.sh` and `asdd/project_container.py:attach_session`, one
`claude` process runs inside a tmux session named `asdd`; `asdd claude`, `asdd attach`,
and `asdd open` all join it via `docker exec -it … tmux attach -t asdd`. The terminal
therefore talks to **tmux**, and tmux's defaults govern scrolling:

- `history-limit` defaults to **2000 lines** — older output is dropped, so scrollback
  "stops" well before the operator expects.
- `mouse` defaults to **off** — the plain wheel is not bound to scroll, which is why the
  operator resorts to a modifier (Shift) to reach the terminal's own scroll path.

A locally-launched `claude` has neither limit: the terminal emulator itself holds a large
scrollback and the wheel scrolls it natively. So the goal is to make tmux behave like that
emulator.

**Decision**: Configure tmux rather than change any application or CLI code.

## R2 — How to raise retained history

- **Decision**: `set -g history-limit 50000`.
- **Rationale**: 50000 lines is a generous, local-terminal-like depth that easily
  satisfies SC-001 (read back ≥2000 lines) while keeping the per-pane buffer memory
  bounded (order tens of MB worst case, grown lazily as output is produced). Round,
  conventional value widely used for tmux.
- **Critical constraint**: `history-limit` only applies to panes **created after** it is
  set; it does not resize an existing pane. The config must be read **before**
  `tmux new-session` creates the held pane.
- **Mechanism**: tmux reads its global config (`/etc/tmux.conf`) at **server start**.
  `asdd-session.sh` starts the server with `tmux new-session -d -s asdd "$0 --inner"`;
  the server reads `/etc/tmux.conf` fully, then creates the session — so the held pane is
  born with `history-limit 50000`. No edit to `asdd-session.sh` is required.
- **Alternatives considered**:
  - *Per-session `tmux set-option` in `asdd-session.sh`*: would require ordering the
    `set` before `new-session` (a second `tmux` invocation to the not-yet-started server)
    or `new-session … \; set-option`, which is brittle. Rejected — config file is simpler
    and declarative.
  - *`~/.tmux.conf` in the asdd user home*: works, but `/home/asdd` is partly a bind-mount
    target for per-project state; `/etc/tmux.conf` is mount-independent and unambiguous.
    Chosen `/etc/tmux.conf`.
  - *Unbounded history*: rejected — memory growth on a long-lived persistent session must
    stay bounded (spec assumption).

## R3 — Natural mouse-wheel scrolling

- **Decision**: `set -g mouse on`.
- **Rationale**: With mouse on, rolling the wheel over the pane enters tmux copy-mode and
  scrolls the (now large) history directly, with no modifier key — matching FR-003.
  Scrolling back to the bottom / new output returns to the live view (FR-004), and
  copy-mode stops cleanly at buffer boundaries (FR-005).
- **Interaction risk — application mouse capture**: if the foreground app requests mouse
  tracking (DECSET 1000/1006), tmux forwards wheel events to the app instead of scrolling.
  Claude Code's TUI writes to the main screen (not the alternate screen — confirmed by the
  fact that today's Shift+wheel reaches scrollback at all) and does not take over wheel
  scroll, so `mouse on` yields tmux history scrolling. **This is the main thing the
  integration/quickstart validation must confirm on a real image**; if a future Claude
  version captures the wheel, the larger `history-limit` still fixes the Shift+wheel path,
  and an explicit `bind -n WheelUpPane … copy-mode` could be added. Documented as a
  watch-point, not a blocker.

## R4 — Preserve copy/paste, detach, and remote parity

- **Copy-out (FR-006)**: With `mouse on`, drag-select enters tmux copy-mode and yields a
  tmux buffer; to copy into the macOS system clipboard the operator holds their terminal's
  bypass modifier (Option/Shift, terminal-dependent) for a native selection. This is
  standard tmux behaviour and keeps copy usable. We also set
  `set -g mode-keys vi` and a sane copy-mode selection so in-tmux yank works, but we do
  **not** add an OSC-52 / external clipboard integration (out of scope, and the container
  has no host clipboard). Decision: rely on the terminal bypass modifier for system-clipboard
  copy; document it in quickstart.
- **Detach (FR-007)**: `mouse on` does not touch the prefix or `detach-client` binding;
  Ctrl-b d still detaches and leaves `claude` running. No change.
- **Remote/mobile parity (FR-009, edge case)**: mouse and history are local tmux-client /
  pane concerns; `claude --remote-control` is an outbound bridge unaffected by them. No
  inbound port is added. Confirmed against the no-listener invariant.

## R5 — Consistency across entry points (FR-008)

All three entry points attach to the **same** server and the **same** pane:
`mouse on` is server-global (`set -g`) and the pane's `history-limit` was fixed at
creation. Therefore `asdd claude`, `asdd attach`, and `asdd open` observe identical
scrolling and history depth with no per-entry-point work.

## R6 — Testing approach

- **Decision**: Two layers.
  - *Unit* (`tests/unit/test_tmux_config.py`): assert `docker/files/asdd-tmux.conf` exists
    and contains `history-limit 50000` and `mouse on`, and assert `docker/Dockerfile.project`
    copies it to `/etc/tmux.conf`. Pure file assertions — no docker needed; matches the
    repo's existing static-asset test style.
  - *Integration* (`tests/integration/test_scrollback_history.py`, docker-gated): build/run
    the image, start a tmux server using the baked config, and assert
    `tmux show-options -g history-limit` and `… mouse` report the configured values; skips
    cleanly when docker is unavailable (per the project's integration-test convention).
- **Rationale**: The unit layer locks the contract cheaply and always runs in CI; the
  integration layer proves the config actually takes effect in a real tmux server.

## Resolved unknowns

All Technical Context items are resolved; no `NEEDS CLARIFICATION` remains. The one tunable
(history depth) is fixed at **50000 lines** with rationale above.
