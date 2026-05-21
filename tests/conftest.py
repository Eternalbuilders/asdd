"""Minimal pytest config for the asdd repo.

Skip @pytest.mark.docker tests when no docker daemon is reachable, so the
unit-test sweep runs cleanly in environments without Docker.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def asdd_home(tmp_path: Path) -> Path:
    """A freshly-initialised ${ASDD_HOME} under tmp_path."""
    from asdd import bootstrap

    home = tmp_path / "asdd-home"
    bootstrap.cmd_init(asdd_home=home)
    return home


@pytest.fixture
def asdd_home_with_project(asdd_home: Path) -> Path:
    """An initialised home with one active project ``vaultcontrol`` whose
    workspace directory exists on disk.

    This fixture was lost in the monorepo extraction; the integration tests
    reference it. Building it directly (registry row + workspace dir) keeps
    it cheap and avoids needing git/docker at fixture setup.
    """
    from asdd import bootstrap

    project_id = "vaultcontrol"
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
    return asdd_home


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return (
            subprocess.run(
                ["docker", "version"],
                capture_output=True,
                text=True,
                timeout=5,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


_DOCKER_OK = _docker_available()


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    if _DOCKER_OK:
        return
    skip = pytest.mark.skip(reason="docker daemon not reachable")
    for item in items:
        if "docker" in item.keywords:
            item.add_marker(skip)
