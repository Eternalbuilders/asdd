# Contract: Attached-Session Scrolling Behaviour

This is the behavioural contract the project image guarantees for any operator-attached
interactive Claude session (`asdd claude`, `asdd attach`, `asdd open`). It is realised by
`/etc/tmux.conf` baked into `asdd/project:latest`.

## Configuration surface (`/etc/tmux.conf`)

The image MUST ship a global tmux config that sets, at minimum:

```tmux
set -g history-limit 50000
set -g mouse on
set -g mode-keys vi
```

- These are server-global (`set -g`) and are read at tmux **server start** (the
  `tmux new-session` in `asdd-session.sh`), so the held pane is created with the full
  history depth.
- The file is the single source for these values; tests assert exactly these options.

## Guaranteed behaviour

| ID | Guarantee | Verifiable by |
|----|-----------|---------------|
| C1 | A freshly held session pane has `history-limit` = 50000. | `tmux show-options -g history-limit` → `history-limit 50000` |
| C2 | Mouse input is enabled server-wide. | `tmux show-options -g mouse` → `mouse on` |
| C3 | Rolling the mouse wheel up over the pane scrolls into retained history with no modifier key. | Manual / quickstart |
| C4 | Scrolling to the bottom, or arrival of new output, returns the view to the live tail. | Manual / quickstart |
| C5 | Scrolling stops cleanly at the top/bottom of the buffer (no error, no detach). | Manual / quickstart |
| C6 | Ctrl-b d still detaches and leaves `claude` running (mobile/web visibility preserved). | `asdd ps` shows session still up after detach |
| C7 | All three entry points observe identical history depth and mouse behaviour. | Attach via each; compare C1–C5 |
| C8 | No inbound network port is opened by this configuration. | `docker port <container>` shows no new mapping |

## Non-goals (explicitly out of contract)

- System-clipboard integration from inside the container (no OSC-52 / host clipboard
  bridge). System-clipboard copy is achieved via the operator terminal's bypass modifier
  during selection; this contract does not change that.
- Any change to the mobile/web remote-control experience.
- Persisting scrollback across session restarts.
