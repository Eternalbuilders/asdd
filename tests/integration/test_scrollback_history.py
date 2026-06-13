"""Integration proof for spec 005 (scrollback-history).

Docker-gated (``@pytest.mark.docker``): the dev container with no docker
socket skips these cleanly, matching the project's integration-test
convention (see ``tests/conftest.py``).

Where the unit layer (``tests/unit/test_tmux_config.py``) asserts the config
*file* and the Dockerfile COPY, this layer proves the config actually *takes
effect*: it starts a real tmux server inside the built image — exactly as
``docker/files/asdd-session.sh`` does with ``tmux new-session`` — and reads the
server-global options tmux loaded from the baked ``/etc/tmux.conf``.

Maps to contract C1 (history-limit 50000) and C2 (mouse on) in
``specs/005-scrollback-history/contracts/tmux-session.md``.
"""

from __future__ import annotations

import subprocess

import pytest

from asdd import project_container as pc

pytestmark = pytest.mark.docker


# T012 / contract C7 — cross-entry-point consistency, as actually wired:
#
#   * `asdd claude` and `asdd attach` both call
#     project_container.attach_session() -> `tmux attach -t asdd`, joining the
#     ONE held claude pane. They therefore observe the server-global options
#     proved below (history-limit 50000, mouse on).
#   * `asdd open` calls attach_shell() -> `docker exec -it <c> bash`, a plain
#     side-shell with NO tmux. Its scrollback is the operator terminal's own
#     (already long + mouse-native) — the very baseline this feature restores
#     for the tmux paths. So behaviour is consistent across all three entry
#     points; the mechanism differs (tmux config vs native terminal).
#
# Net: the only paths that were ever scroll-limited are the tmux ones, and
# both share this single server-global config. No per-entry-point work needed.


def _server_global_option(name: str) -> str:
    """Start a tmux server inside the image (which loads /etc/tmux.conf at
    server start, just like asdd-session.sh's `tmux new-session`), read back a
    server-global option, then tear the server down. Returns the option value
    (the token after the option name), e.g. "50000" for history-limit.

    Because the option is server-global (`set -g`), its value is identical no
    matter which entry point (`asdd claude` / `asdd attach` / `asdd open`)
    later attaches to the held pane — they all join this one server (T012/C7).
    """
    pc.ensure_image_built()
    script = (
        # new-session -d starts the server -> /etc/tmux.conf is read here, so
        # the pane is born with the configured history depth.
        "tmux new-session -d -s probe 'sleep 30'; "
        f"tmux show-options -g {name}; "
        "tmux kill-server"
    )
    proc = subprocess.run(
        ["docker", "run", "--rm", pc.IMAGE_NAME, "bash", "-lc", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"docker run failed: {proc.stderr}"
    # `show-options -g <name>` prints e.g. "history-limit 50000".
    for line in proc.stdout.splitlines():
        parts = line.split(None, 1)
        if parts and parts[0] == name:
            return parts[1].strip() if len(parts) > 1 else ""
    raise AssertionError(f"option {name!r} not reported by tmux: {proc.stdout!r}")


def test_history_limit_is_50000_on_live_server() -> None:
    """Contract C1 / SC-001: the held pane has a long scrollback (50000)."""
    assert _server_global_option("history-limit") == "50000"


def test_mouse_is_on_on_live_server() -> None:
    """Contract C2 / SC-002: mouse input is enabled server-wide, so a plain
    wheel gesture scrolls history with no modifier key."""
    assert _server_global_option("mouse") == "on"


def test_mode_keys_vi_on_live_server() -> None:
    """Foundational baseline loaded from /etc/tmux.conf at server start."""
    assert _server_global_option("mode-keys") == "vi"
