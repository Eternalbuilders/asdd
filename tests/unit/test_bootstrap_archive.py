"""Unit tests for spec 003 US3 — cmd_archive removes per-project Claude state.

Mocks supervisor + container teardown so the test exercises only the
archive cleanup behaviour, not Docker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from asdd import auth, bootstrap, project_container, supervisor


def _add_project(asdd_home: Path, project_id: str) -> None:
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


def _stub_teardown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub supervisor + container ops; cmd_archive needs them to no-op."""
    monkeypatch.setattr(supervisor, "uninstall", lambda pid: None)
    monkeypatch.setattr(project_container, "stop_container", lambda pid: True)
    monkeypatch.setattr(project_container, "remove_container", lambda pid, **k: True)


def test_cmd_archive_removes_per_project_claude_state(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 003 FR-005 / SC-004: archiving a project removes its
    per-project Claude state subtree."""
    _stub_teardown(monkeypatch)
    _add_project(asdd_home, "alpha")
    _add_project(asdd_home, "beta")

    # Materialise both subtrees with sentinel content.
    auth.ensure_mountable(asdd_home, project_id="alpha")
    auth.ensure_mountable(asdd_home, project_id="beta")
    (auth.per_project_dir(asdd_home, "alpha") / "marker.txt").write_text("alpha")
    (auth.per_project_dir(asdd_home, "beta") / "marker.txt").write_text("beta")

    bootstrap.cmd_archive(asdd_home=asdd_home, project_id="alpha")

    assert not auth.per_project_dir(asdd_home, "alpha").exists()
    # beta's subtree must be untouched.
    assert auth.per_project_dir(asdd_home, "beta").is_dir()
    assert (auth.per_project_dir(asdd_home, "beta") / "marker.txt").read_text() == "beta"


def test_cmd_archive_idempotent_when_per_project_state_absent(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project that never started a container has no per-project subtree.
    Archive must succeed regardless."""
    _stub_teardown(monkeypatch)
    _add_project(asdd_home, "gamma")
    assert not auth.per_project_dir(asdd_home, "gamma").exists()

    # Must not raise.
    bootstrap.cmd_archive(asdd_home=asdd_home, project_id="gamma")
