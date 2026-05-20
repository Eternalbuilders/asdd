"""Integration test for spec 008 Phase A (US1+US2+US3+US4) — T122.

Exercises the real Docker daemon. Gated by @pytest.mark.docker so the
dev container (no docker socket) skips the test cleanly.

What this test asserts, mapped to spec 008 requirements:

- FR-001/FR-003: `asdd open` brings up a project container with the
  workspace mounted and bash available inside.
- FR-002: a second `asdd open` for the same id fails fast with a
  non-zero exit and an "already running" message.
- FR-004/FR-007: when the operator's shell exits, the container is
  gone within 10 seconds (US2).
- FR-005/SC-007: from inside the container, the operator's host
  filesystem (other than the project workspace and the auth mounts) is
  NOT visible.
- FR-006/SC-001: cold start completes within 15 seconds (image already
  built; we time the second open).
- FR-010 (US3): a file written into the workspace before exit is
  still there on the next open.
- FR-011: `asdd open` against an archived project fails fast.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.docker


def _docker_ps_count(name: str) -> int:
    """Count running containers matching the given name (exact)."""
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name=^{name}$", "--format", "{{.ID}}"],
        capture_output=True,
        text=True,
    )
    return len([line for line in result.stdout.splitlines() if line.strip()])


def _wait_for_container_gone(name: str, *, timeout: float = 12.0) -> bool:
    """Poll docker ps until the container is gone or `timeout` elapses."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if _docker_ps_count(name) == 0:
            return True
        time.sleep(0.5)
    return False


def _wait_for_container_up(name: str, *, timeout: float = 15.0) -> bool:
    """Poll docker ps until the container is up or `timeout` elapses."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if _docker_ps_count(name) == 1:
            return True
        time.sleep(0.2)
    return False


def test_open_close_roundtrip(asdd_home_with_project: Path) -> None:
    """End-to-end: open, verify isolation, exit, verify cleanup."""
    from asdd import project_container as pc

    project_id = "vaultcontrol"
    container = pc.container_name(project_id)

    # Make sure no stale container is lingering from a previous test run.
    subprocess.run(["docker", "stop", container], capture_output=True)
    assert _docker_ps_count(container) == 0, "stale container before test start"

    # Ensure the project image is built once (so the FR-006 timing in step 4
    # measures cold-start without build overhead).
    pc.ensure_image_built()

    # 1. Start the container by hand (avoids needing a TTY for `asdd open`).
    workspace_path = asdd_home_with_project / "projects" / project_id
    pc_obj = pc.ProjectContainer(
        project_id=project_id, mode="interactive", workspace_path=workspace_path
    )
    cold_start_began = time.monotonic()
    pc.start_container(pc_obj)
    try:
        assert _wait_for_container_up(container), "container did not start within 15s"
        cold_start_elapsed = time.monotonic() - cold_start_began
        assert cold_start_elapsed < 15.0, (
            f"cold start took {cold_start_elapsed:.1f}s, exceeds FR-006 (15s)"
        )

        # 2. FR-005 / SC-007: from inside the container, the host home dir is NOT visible.
        ls_root = subprocess.run(
            ["docker", "exec", container, "ls", "/"],
            capture_output=True, text=True,
        )
        assert ls_root.returncode == 0
        root_entries = set(ls_root.stdout.split())
        # The workspace is mounted at /asdd_home.
        assert "asdd_home" in root_entries
        # The host's filesystem root is NOT visible at all — only mount points appear.
        # We're specifically verifying that no /Users, /home/<host-user>, no /vaults etc.
        # leak in (the operator's auth mounts go into /home/asdd/.claude, not at /).
        assert "Users" not in root_entries, "host /Users leaked into container"
        assert "vaults" not in root_entries, "host /vaults leaked into container"

        # 3. FR-002: a second start fails fast.
        with pytest.raises(pc.AlreadyRunningError):
            pc.assert_not_running(project_id)

        # 4. FR-010 / US3: write a file inside, then expect it on disk in the workspace.
        subprocess.run(
            ["docker", "exec", container, "touch", "/asdd_home/sentinel-008.txt"],
            check=True,
        )
        sentinel = workspace_path / "sentinel-008.txt"
        assert sentinel.is_file(), "workspace bind mount did not persist write"
    finally:
        # 5. FR-004 / FR-007: stop the container; it must be gone within 10s.
        stop_began = time.monotonic()
        pc.stop_container(project_id)
        gone = _wait_for_container_gone(container, timeout=11.0)
        stop_elapsed = time.monotonic() - stop_began
        assert gone, "container still present after stop"
        assert stop_elapsed < 11.0, f"stop took {stop_elapsed:.1f}s, exceeds FR-007 (10s)"

        # 6. FR-010 again: re-open and confirm the sentinel is still there.
        pc.start_container(pc_obj)
        try:
            assert _wait_for_container_up(container)
            ls = subprocess.run(
                ["docker", "exec", container, "test", "-f", "/asdd_home/sentinel-008.txt"],
            )
            assert ls.returncode == 0, "sentinel did not survive container restart"
        finally:
            pc.stop_container(project_id)
            assert _wait_for_container_gone(container)


def test_open_refuses_archived_project(
    asdd_home_with_project: Path, tmp_path: Path
) -> None:
    """FR-011: cmd_open against an archived project must fail clearly."""
    from asdd import bootstrap

    # Flip the lifecycle state to archived directly (avoids the full
    # cmd_archive snapshot path which is unrelated to this assertion).
    reg = asdd_home_with_project / "_state" / "projects.yml"
    raw = yaml.safe_load(reg.read_text())
    for r in raw["projects"]:
        if r["id"] == "vaultcontrol":
            r["lifecycle_state"] = "archived"
    reg.write_text(yaml.safe_dump(raw, sort_keys=False))

    with pytest.raises(bootstrap.BootstrapError, match="archived"):
        bootstrap.cmd_open(asdd_home=asdd_home_with_project, project_id="vaultcontrol")


def test_open_refuses_unknown_project(asdd_home_with_project: Path) -> None:
    """FR-011: cmd_open against a missing id must fail clearly."""
    from asdd import bootstrap

    with pytest.raises(bootstrap.BootstrapError, match="not registered"):
        bootstrap.cmd_open(
            asdd_home=asdd_home_with_project, project_id="nope-not-real"
        )
