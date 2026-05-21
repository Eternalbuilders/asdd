"""Integration tests for spec 009 — subscription auth across modes.

Gated by @pytest.mark.docker; skipped where no docker socket. These use a
seeded credential store (a fake login written into the asdd-owned store) and
ASDD_JOB_STUB_OUTPUT so no live Claude call or real subscription is needed —
they assert the *mechanism* (store mounted, no API key required, refresh
written back), not real authentication.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from asdd import auth, bootstrap
from asdd import project_container as pc

pytestmark = pytest.mark.docker


def _seed_fake_store(asdd_home: Path) -> None:
    """Write a minimal credential store directly (no host dependency)."""
    auth.prepare_empty_store(asdd_home)
    auth.store_json_path(asdd_home).write_text(json.dumps({"email": "ci@example.com"}))
    auth.credentials_file(asdd_home).write_text(json.dumps({"accessToken": "ci-tok"}))
    auth.mark_fresh_login(asdd_home)


def _wait_for_gone(name: str, *, timeout: float = 12.0) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        r = subprocess.run(
            ["docker", "ps", "--filter", f"name=^{name}$", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
        )
        if not r.stdout.strip():
            return True
        time.sleep(0.5)
    return False


def test_us2_dispatch_on_subscription_without_api_key(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """US2: with a store present and NO API key, dispatch produces a result."""
    project_id = "vaultcontrol"
    subprocess.run(["docker", "stop", pc.container_name(project_id)], capture_output=True)
    _seed_fake_store(asdd_home_with_project)

    ws = asdd_home_with_project / "projects" / project_id
    (ws / "inbox").mkdir(parents=True, exist_ok=True)
    job = ws / "inbox" / "smoke.md"
    job.write_text("# job\n\nsmoke\n")

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ASDD_JOB_STUB_OUTPUT", "stub-on-subscription")

    pc.ensure_image_built()
    result = bootstrap.cmd_dispatch(
        asdd_home=asdd_home_with_project, project_id=project_id, job_path=job
    )
    assert result.is_file()
    assert result.read_text().strip() == "stub-on-subscription"
    assert _wait_for_gone(pc.container_name(project_id))


def test_us2_dispatch_fails_fast_without_login(asdd_home_with_project: Path) -> None:
    """US2 AS3: no store, no key → fail fast naming `asdd login`, no hang."""
    ws = asdd_home_with_project / "projects" / "vaultcontrol"
    (ws / "inbox").mkdir(parents=True, exist_ok=True)
    job = ws / "inbox" / "smoke.md"
    job.write_text("# job\n")
    with pytest.raises(bootstrap.BootstrapError, match="no subscription login"):
        bootstrap.cmd_dispatch(
            asdd_home=asdd_home_with_project, project_id="vaultcontrol", job_path=job
        )


def test_us1_open_mounts_store(
    asdd_home_with_project: Path,
) -> None:
    """US1: an interactive container started with asdd_home set mounts the
    credential store at /home/asdd/.claude.json (verified via docker inspect)."""
    project_id = "vaultcontrol"
    container = pc.container_name(project_id)
    subprocess.run(["docker", "stop", container], capture_output=True)
    _seed_fake_store(asdd_home_with_project)

    pc.ensure_image_built()
    obj = pc.ProjectContainer(
        project_id=project_id,
        mode="interactive",
        workspace_path=asdd_home_with_project / "projects" / project_id,
        asdd_home=asdd_home_with_project,
    )
    pc.start_container(obj)
    try:
        out = subprocess.run(
            ["docker", "exec", container, "cat", "/home/asdd/.claude.json"],
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0
        assert "ci@example.com" in out.stdout
    finally:
        pc.stop_container(project_id)


def test_us3_refresh_written_back_to_store(
    asdd_home_with_project: Path,
) -> None:
    """US3: a write to the mounted store from inside a container persists for
    the next container start (rw bind-mount write-back)."""
    project_id = "vaultcontrol"
    container = pc.container_name(project_id)
    subprocess.run(["docker", "stop", container], capture_output=True)
    _seed_fake_store(asdd_home_with_project)

    pc.ensure_image_built()
    obj = pc.ProjectContainer(
        project_id=project_id,
        mode="interactive",
        workspace_path=asdd_home_with_project / "projects" / project_id,
        asdd_home=asdd_home_with_project,
    )
    pc.start_container(obj)
    try:
        subprocess.run(
            ["docker", "exec", container, "sh", "-c",
             "echo '{\"email\":\"refreshed@example.com\"}' > /home/asdd/.claude.json"],
            check=True,
        )
    finally:
        pc.stop_container(project_id)

    # The host-side store reflects the in-container write.
    assert "refreshed@example.com" in auth.store_json_path(asdd_home_with_project).read_text()
