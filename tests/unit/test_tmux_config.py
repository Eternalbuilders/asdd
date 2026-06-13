"""Static assertions for the baked tmux config (spec 005 scrollback-history).

Pure file checks — no docker needed, always runs in CI. Locks the contract in
``specs/005-scrollback-history/contracts/tmux-session.md``: the image ships a
global tmux config setting a long ``history-limit`` and ``mouse on``, and the
project Dockerfile copies it to ``/etc/tmux.conf`` so tmux loads it at server
start. The live-server proof lives in
``tests/integration/test_scrollback_history.py``.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TMUX_CONF = REPO_ROOT / "docker" / "files" / "asdd-tmux.conf"
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile.project"


def test_tmux_conf_exists() -> None:
    """The config asset must be present to be baked into the image."""
    assert TMUX_CONF.is_file(), f"missing {TMUX_CONF}"


def test_dockerfile_copies_conf_to_etc_tmux_conf() -> None:
    """T004 / contract: the image must place the config at /etc/tmux.conf so
    tmux auto-loads it at server start (the `tmux new-session` in
    asdd-session.sh). Without this, the held pane keeps tmux defaults."""
    text = DOCKERFILE.read_text()
    assert "docker/files/asdd-tmux.conf /etc/tmux.conf" in text, (
        "Dockerfile.project must COPY docker/files/asdd-tmux.conf to /etc/tmux.conf"
    )


def test_history_limit_is_50000() -> None:
    """US1 / contract C1: long scrollback. Must be a global `set -g` so it is
    read before the held pane is created (history-limit does not resize an
    existing pane)."""
    assert "set -g history-limit 50000" in TMUX_CONF.read_text()


def test_mouse_is_on() -> None:
    """US2 / contract C2: natural mouse-wheel scrolling with no modifier."""
    assert "set -g mouse on" in TMUX_CONF.read_text()


def test_mode_keys_vi() -> None:
    """Foundational baseline: predictable copy-mode navigation."""
    assert "set -g mode-keys vi" in TMUX_CONF.read_text()
