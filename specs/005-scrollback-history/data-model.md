# Phase 1 Data Model: Long, Naturally-Scrollable Session History

This feature introduces no application data entities. The "model" is the small set of
declarative session-behaviour parameters carried by the baked tmux configuration. They are
captured here so the contract and tests have a single source of truth.

## Configuration parameters

| Parameter | tmux option | Value | Constraint / rule |
|-----------|-------------|-------|-------------------|
| Retained history depth | `history-limit` | `50000` | Set globally (`set -g`) and read **before** the held pane is created, so the pane is born with this depth. Bounded ring buffer; oldest lines discarded past the limit. Must be ≥ SC-001's 2000-line read-back floor. |
| Mouse scrolling | `mouse` | `on` | Server-global; enables wheel-to-history with no modifier key and click/drag selection in copy-mode. |
| Copy-mode key style | `mode-keys` | `vi` | Predictable copy-mode navigation; does not affect detach or the prefix. |

## Conceptual entities (from the spec)

- **Attached session**: the operator's tmux client joined to the project's held `claude`
  pane. Relevant attributes are exactly the parameters above (history depth, mouse input
  behaviour). One held pane per project container (existing invariant); all entry points
  attach to it.
- **Scrollback history**: the per-pane in-memory ring buffer of past output. Size bounded
  by `history-limit`; FIFO eviction of the oldest lines once full. Not persisted — it is
  reset only when the pane/process is recreated (e.g. session restart / `--reload`).

## State transitions

- **Live → scrolled-back**: wheel-up (or prefix + `[`) enters copy-mode; the view detaches
  from the live tail and moves through retained history.
- **Scrolled-back → live**: scrolling to the bottom, pressing `q`, or new output arriving
  returns the view to the live tail.
- **History full**: once `history-limit` is reached, each new line evicts the oldest; no
  error, no effect on the live session.
