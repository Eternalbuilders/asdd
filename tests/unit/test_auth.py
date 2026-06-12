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


# --- spec 003 path helpers -------------------------------------------------


def test_per_project_dir_path_shape(tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    assert auth.per_project_root(home) == auth.store_dir(home) / "per-project"
    assert auth.per_project_dir(home, "p") == auth.per_project_root(home) / "p"


def test_legacy_notice_marker_path(tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    assert auth.legacy_notice_marker(home) == auth.store_dir(home) / ".migration-notice-shown"


def test_legacy_state_present_negative_on_empty_store(tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    assert auth.legacy_state_present(home) is False


def test_legacy_state_present_positive_when_claude_projects_exists(tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    (auth.store_claude_dir(home) / "projects").mkdir(parents=True)
    assert auth.legacy_state_present(home) is True


def test_ensure_workspace_trusted_creates_and_merges(tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    # Pre-existing config must be preserved (merge, not clobber).
    auth.prepare_empty_store(home)
    auth.store_json_path(home).write_text(json.dumps({"oauthAccount": {"email": "m@x.no"}}))

    auth.ensure_workspace_trusted(home, "/asdd_home")
    data = json.loads(auth.store_json_path(home).read_text())
    assert data["projects"]["/asdd_home"]["hasTrustDialogAccepted"] is True
    assert data["oauthAccount"]["email"] == "m@x.no"  # untouched

    # Idempotent and does not disturb other projects.
    auth.ensure_workspace_trusted(home, "/asdd_home")
    data = json.loads(auth.store_json_path(home).read_text())
    assert list(data["projects"]) == ["/asdd_home"]
    # 0600 — the store holds the live login config.
    assert stat.S_IMODE(auth.store_json_path(home).stat().st_mode) == 0o600


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


# --- Docker mount-target healing -------------------------------------------


def test_seed_from_host_heals_dir_shaped_claude_json(fake_host: Path, tmp_path: Path) -> None:
    """A container that mounted the store before login left ``claude.json`` as a
    Docker-created directory; seed must heal it instead of raising
    IsADirectoryError (the bug this fix addresses)."""
    home = tmp_path / "asdd-home"
    # Reproduce the Docker footprint: empty directories at both mount targets.
    auth.store_json_path(home).mkdir(parents=True)
    auth.store_claude_dir(home).mkdir(parents=True)

    auth.seed_from_host(home)  # must not raise

    assert auth.store_json_path(home).is_file()
    assert auth.is_logged_in(home) is True


def test_ensure_mountable_materialises_correct_types(tmp_path: Path) -> None:
    """Before any login, ensure_mountable leaves a file + dir so Docker never
    auto-creates a directory at the claude.json target."""
    home = tmp_path / "asdd-home"
    auth.ensure_mountable(home)
    assert auth.store_json_path(home).is_file()
    assert auth.store_claude_dir(home).is_dir()
    assert stat.S_IMODE(auth.store_json_path(home).stat().st_mode) == 0o600
    assert stat.S_IMODE(auth.store_claude_dir(home).stat().st_mode) == 0o700


def test_ensure_mountable_heals_dir_and_is_non_destructive(tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    # A stray Docker-created directory is healed back into a placeholder file.
    auth.store_json_path(home).mkdir(parents=True)
    auth.ensure_mountable(home)
    assert auth.store_json_path(home).is_file()

    # A real seeded credential must survive a later ensure_mountable call.
    auth.store_json_path(home).write_text(json.dumps({"oauthAccount": {"x": 1}}))
    auth.ensure_mountable(home)
    assert json.loads(auth.store_json_path(home).read_text()) == {"oauthAccount": {"x": 1}}


def test_ensure_mountable_creates_credentials_placeholder_when_missing(tmp_path: Path) -> None:
    """Spec 003 R3: a missing .credentials.json target would be auto-created by
    Docker as a directory when we file-bind-mount it; ensure_mountable
    materialises it as an empty 0600 file first."""
    home = tmp_path / "asdd-home"
    auth.ensure_mountable(home)
    cf = auth.credentials_file(home)
    assert cf.is_file()
    assert stat.S_IMODE(cf.stat().st_mode) == 0o600


def test_ensure_mountable_does_not_clobber_existing_credentials(tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    auth.ensure_mountable(home)
    cf = auth.credentials_file(home)
    cf.write_text('{"accessToken":"real"}')
    auth.ensure_mountable(home)
    assert cf.read_text() == '{"accessToken":"real"}'


def test_ensure_mountable_materialises_per_project_dir(tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    auth.ensure_mountable(home, project_id="p")
    pp = auth.per_project_dir(home, "p")
    assert pp.is_dir()
    assert stat.S_IMODE(pp.stat().st_mode) == 0o700


def test_ensure_mountable_no_project_id_skips_per_project(tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    auth.ensure_mountable(home)
    assert not auth.per_project_root(home).exists()


# --- clear -----------------------------------------------------------------


def test_clear_is_idempotent(fake_host: Path, tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    auth.seed_from_host(home)
    assert auth.clear(home) is True
    assert auth.is_logged_in(home) is False
    assert auth.clear(home) is False  # already gone


def test_clear_removes_per_project_subtrees(fake_host: Path, tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    auth.seed_from_host(home)
    auth.ensure_mountable(home, project_id="alpha")
    auth.ensure_mountable(home, project_id="beta")
    assert auth.per_project_dir(home, "alpha").is_dir()
    assert auth.per_project_dir(home, "beta").is_dir()

    assert auth.clear(home) is True
    assert not auth.per_project_root(home).exists()
    assert not auth.store_dir(home).exists()


def test_clear_removes_legacy_notice_marker(fake_host: Path, tmp_path: Path) -> None:
    home = tmp_path / "asdd-home"
    auth.seed_from_host(home)
    auth.legacy_notice_marker(home).write_text("")
    assert auth.legacy_notice_marker(home).exists()

    assert auth.clear(home) is True
    assert not auth.legacy_notice_marker(home).exists()


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
