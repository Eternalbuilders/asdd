"""Unit tests for the subscription credential store (spec 009).

Pure-Python; no docker, no network. Exercises path helpers, seed-from-host,
status parsing, clear idempotency, permissions, the advisory lock, and the
FR-008 invariant that the store never lives under a project workspace.
"""

from __future__ import annotations

import json
import stat
import threading
import time
from pathlib import Path

import pytest

from asdd import auth


@pytest.fixture
def fake_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake host HOME with a *file-based* Claude Code login present
    (config + a real .credentials.json, as on Linux / keychain-disabled)."""
    host = tmp_path / "host-home"
    host.mkdir()
    (host / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "marius@example.com"},
                    "claudeAiOauth": {"expiresAt": "2026-12-31T00:00:00Z"}})
    )
    cdir = host / ".claude"
    cdir.mkdir()
    (cdir / "settings.json").write_text("{}")
    (cdir / ".credentials.json").write_text(json.dumps({"accessToken": "tok-123"}))
    monkeypatch.setenv("HOME", str(host))
    return host


# --- paths -----------------------------------------------------------------


def test_store_paths(tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    assert auth.store_dir(home) == home / "_state" / "claude-auth"
    assert auth.store_json_path(home) == auth.store_dir(home) / "claude.json"
    assert auth.store_claude_dir(home) == auth.store_dir(home) / "claude"


def test_not_logged_in_on_empty_home(tmp_path: Path) -> None:
    assert auth.is_logged_in(tmp_path / "asdd-home") is False
    st = auth.status(tmp_path / "asdd-home")
    assert st.logged_in is False
    assert st.source is None


# --- seed-from-host --------------------------------------------------------


def test_seed_from_host_copies_and_logs_in(fake_host: Path, tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    assert auth.host_login_present() is True
    auth.seed_from_host(home)

    assert auth.is_logged_in(home) is True
    assert auth.store_json_path(home).is_file()
    assert (auth.store_claude_dir(home) / "settings.json").is_file()

    st = auth.status(home)
    assert st.logged_in is True
    assert st.source == auth.SOURCE_SEEDED
    assert st.identity == "marius@example.com"
    assert st.expiry == "2026-12-31T00:00:00Z"


def test_seed_from_host_raises_without_host_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    (tmp_path / "empty-home").mkdir()
    with pytest.raises(auth.AuthError, match="no host Claude login"):
        auth.seed_from_host(tmp_path / "asdd-home")


def test_seed_config_only_has_no_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """macOS case: host has config but the token is in Keychain (no
    .credentials.json), so the seeded store is NOT actually logged in."""
    host = tmp_path / "host-home"
    (host / ".claude").mkdir(parents=True)
    (host / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "m@x.z"}}))
    monkeypatch.setenv("HOME", str(host))

    home = tmp_path / "asdd-home"
    auth.seed_from_host(home)  # copies config, but no .credentials.json
    assert auth.has_credential(home) is False
    assert auth.is_logged_in(home) is False


def test_store_permissions(fake_host: Path, tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    auth.seed_from_host(home)
    dmode = stat.S_IMODE(auth.store_dir(home).stat().st_mode)
    jmode = stat.S_IMODE(auth.store_json_path(home).stat().st_mode)
    assert dmode == 0o700
    assert jmode == 0o600


# --- clear -----------------------------------------------------------------


def test_clear_is_idempotent(fake_host: Path, tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    auth.seed_from_host(home)
    assert auth.clear(home) is True
    assert auth.is_logged_in(home) is False
    assert auth.clear(home) is False  # already gone


# --- fresh-login marker ----------------------------------------------------


def test_mark_fresh_login_requires_real_credential(tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    auth.prepare_empty_store(home)
    # An empty store has no real credential — marking fresh must refuse.
    assert auth.is_logged_in(home) is False
    with pytest.raises(auth.AuthError):
        auth.mark_fresh_login(home)
    # Simulate the in-container login writing the credential, then it works.
    auth.credentials_file(home).write_text(json.dumps({"accessToken": "tok"}))
    auth.mark_fresh_login(home)
    assert auth.status(home).source == auth.SOURCE_FRESH


# --- advisory lock ---------------------------------------------------------


def test_store_lock_serializes(tmp_path: Path) -> None:
    """Two threads contending on the lock must not overlap inside it."""
    home = tmp_path / "asdd-home"
    order: list[str] = []

    def worker(tag: str) -> None:
        with auth.store_lock(home):
            order.append(f"{tag}-enter")
            time.sleep(0.05)
            order.append(f"{tag}-exit")

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start()
    time.sleep(0.01)  # ensure t1 grabs the lock first
    t2.start()
    t1.join()
    t2.join()

    # Whoever entered first must exit before the other enters (no interleave).
    assert order[0].endswith("-enter")
    assert order[1].endswith("-exit")
    assert order[0].split("-")[0] == order[1].split("-")[0]


# --- FR-008: store is never under a project workspace ----------------------


def test_store_not_under_any_workspace(asdd_home_with_project: Path) -> None:
    store = auth.store_dir(asdd_home_with_project)
    workspace = asdd_home_with_project / "projects" / "vaultcontrol"
    assert workspace not in store.parents
    with pytest.raises(ValueError):
        store.relative_to(workspace)
