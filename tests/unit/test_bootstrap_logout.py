"""Spec 004 Phase 6 — cmd_logout tears down running serves before clearing.

Mocks the registry + container/supervisor surface so we exercise only the
teardown-order logic and the refuse-on-failure path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from asdd import bootstrap, project_container, supervisor


def _register(asdd_home: Path, project_id: str) -> None:
    workspace = asdd_home / "projects" / project_id
    workspace.mkdir(parents=True, exist_ok=True)
    raw = bootstrap._read_registry_raw(asdd_home)
    now = bootstrap._iso_utc_now()
    raw["projects"].append(
        {
            "id": project_id,
            "name": project_id,
            "workspace_path": str(workspace),
            "git_remote": None,
            "default_branch": "main",
            "lifecycle_state": "active",
            "created_at": now,
            "last_checked_at": now,
            "description": None,
        }
    )
    bootstrap._write_registry_atomic(asdd_home, raw)


def _seed_real_credential(asdd_home: Path) -> None:
    """auth.clear returns True iff something was removed — give it a real store."""
    import json as _json

    from asdd import auth as _auth

    _auth.prepare_empty_store(asdd_home)
    _auth.credentials_file(asdd_home).write_text(_json.dumps({"accessToken": "x"}))


def _patch_runners(
    monkeypatch: pytest.MonkeyPatch,
    *,
    running: set[str],
    fail_stop: set[str] | None = None,
    fail_uninstall: set[str] | None = None,
) -> list[tuple[str, str]]:
    """Patch supervisor + container teardown to record calls. Returns the
    ordered call log: [(project_id, action), ...]."""
    fail_stop = fail_stop or set()
    fail_uninstall = fail_uninstall or set()
    calls: list[tuple[str, str]] = []

    def fake_uninstall(pid: str) -> bool:
        calls.append((pid, "uninstall"))
        if pid in fail_uninstall:
            raise supervisor.SupervisorError(f"sim failure for {pid}")
        return True

    def fake_stop(pid: str, *, timeout: int = 10) -> bool:
        calls.append((pid, "stop"))
        return pid not in fail_stop

    def fake_remove(pid: str, *, force: bool = False) -> bool:
        calls.append((pid, "remove"))
        return True

    monkeypatch.setattr(supervisor, "uninstall", fake_uninstall)
    monkeypatch.setattr(project_container, "stop_container", fake_stop)
    monkeypatch.setattr(project_container, "remove_container", fake_remove)
    monkeypatch.setattr(
        project_container, "is_persistent_running", lambda pid: pid in running
    )
    return calls


def test_logout_no_running_serves_clears_store(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register(asdd_home, "p1")
    _seed_real_credential(asdd_home)
    calls = _patch_runners(monkeypatch, running=set())

    assert bootstrap.cmd_logout(asdd_home=asdd_home) is True
    assert calls == []  # no teardown attempted


def test_logout_one_running_serve_stops_then_clears(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register(asdd_home, "alpha")
    _seed_real_credential(asdd_home)
    calls = _patch_runners(monkeypatch, running={"alpha"})

    assert bootstrap.cmd_logout(asdd_home=asdd_home) is True
    # Order matters: uninstall → stop → remove (per contracts/asdd-logout.md).
    assert calls == [("alpha", "uninstall"), ("alpha", "stop"), ("alpha", "remove")]


def test_logout_two_running_serves_stops_both_then_clears(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register(asdd_home, "alpha")
    _register(asdd_home, "beta")
    _seed_real_credential(asdd_home)
    calls = _patch_runners(monkeypatch, running={"alpha", "beta"})

    assert bootstrap.cmd_logout(asdd_home=asdd_home) is True
    # Both projects had all three teardown calls before clear.
    a_actions = [a for p, a in calls if p == "alpha"]
    b_actions = [a for p, a in calls if p == "beta"]
    assert a_actions == ["uninstall", "stop", "remove"]
    assert b_actions == ["uninstall", "stop", "remove"]


def test_logout_refuses_when_stop_fails(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asdd import auth as _auth

    _register(asdd_home, "alpha")
    _seed_real_credential(asdd_home)
    _patch_runners(monkeypatch, running={"alpha"}, fail_stop={"alpha"})

    with pytest.raises(bootstrap.BootstrapError, match="refusing to log out"):
        bootstrap.cmd_logout(asdd_home=asdd_home)
    # Credential store MUST still exist.
    assert _auth.is_logged_in(asdd_home) is True


def test_logout_failure_message_names_project(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register(asdd_home, "stuck-one")
    _seed_real_credential(asdd_home)
    _patch_runners(monkeypatch, running={"stuck-one"}, fail_uninstall={"stuck-one"})

    with pytest.raises(bootstrap.BootstrapError) as exc_info:
        bootstrap.cmd_logout(asdd_home=asdd_home)
    assert "stuck-one" in str(exc_info.value)
