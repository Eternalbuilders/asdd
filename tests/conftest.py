"""Minimal pytest config for the asdd repo.

Skip @pytest.mark.docker tests when no docker daemon is reachable, so the
unit-test sweep runs cleanly in environments without Docker.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest


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
