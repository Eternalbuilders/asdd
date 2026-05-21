"""Integration tests for spec 010 — persistent session, container level.

Gated by @pytest.mark.docker; skipped where no docker socket. These exercise
the container-level behaviour (restart policy, detach-safety, dispatch reuse)
directly via `project_container`, bypassing the launchd supervisor — the
launchd/serve/stop/login-and-reboot path is macOS-only and validated
manually via quickstart.md. A fake credential store is seeded so the
persistent mount profile resolves; no live Claude is used.
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


def _seed_store(asdd_home: Path) -> None:
    auth.prepare_empty_store(asdd_home)
    auth.store_json_path(asdd_home).write_text(json.dumps({"email": "ci@example.com"}))
    auth.credentials_file(asdd_home).write_text(json.dumps({"accessToken": "ci-tok"}))
    auth.mark_fresh_login(asdd_home)


def _running(name: str) -> int:
    r = subprocess.run(
        ["docker", "ps", "--filter", f"name=^{name}$", "--format", "{{.ID}}"],
        capture_output=True, text=True,
    )
    return len([ln for ln in r.stdout.splitlines() if ln.strip()])


def _start_persistent(asdd_home: Path, project_id: str, monkeypatch=None) -> None:
    pc.ensure_image_built()
    pc.remove_container(project_id, force=True)
    obj = pc.ProjectContainer(
        project_id=project_id,
        mode="persistent",
        workspace_path=asdd_home / "projects" / project_id,
        asdd_home=asdd_home,
    )
    # Hold the session container up with a sleep instead of a live `claude
    # --remote-control` (no LLM/login in CI) so the restart primitive is what
    # gets exercised.
    if monkeypatch is not None:
        monkeypatch.setenv("ASDD_SESSION_STUB", "1")
    pc.start_container(obj)


def test_persistent_container_persists_and_can_be_restarted(
    asdd_home_with_project: Path, monkeypatch
) -> None:
    """Container-level primitive the launchd babysitter relies on: after a
    kill the persistent container is NOT auto-removed (no --rm) and can be
    `docker start`ed back up. The launchd KeepAlive relaunch that does this
    automatically is macOS-only and validated via quickstart, not here."""
    pid = "vaultcontrol"
    name = pc.container_name(pid)
    _seed_store(asdd_home_with_project)
    _start_persistent(asdd_home_with_project, pid, monkeypatch)
    try:
        assert pc.is_persistent_running(pid)
        subprocess.run(["docker", "kill", name], capture_output=True)
        time.sleep(2)
        # No --rm, no restart policy → it exists but is stopped.
        assert pc.exists(pid)
        assert not pc.is_running(pid)
        # The babysitter's restart primitive brings it back.
        pc.start_existing(pid)
        time.sleep(1)
        assert pc.is_running(pid)
    finally:
        pc.remove_container(pid, force=True)


def test_dispatch_reuses_persistent_container(asdd_home_with_project: Path, monkeypatch) -> None:
    pid = "vaultcontrol"
    name = pc.container_name(pid)
    _seed_store(asdd_home_with_project)
    ws = asdd_home_with_project / "projects" / pid
    (ws / "inbox").mkdir(parents=True, exist_ok=True)
    job = ws / "inbox" / "job.md"
    job.write_text("# job\n")
    monkeypatch.setenv("ASDD_JOB_STUB_OUTPUT", "reused")

    _start_persistent(asdd_home_with_project, pid, monkeypatch)
    try:
        result = bootstrap.cmd_dispatch(
            asdd_home=asdd_home_with_project, project_id=pid, job_path=job
        )
        assert result.read_text().strip() == "reused"
        # Reused the warm container: still exactly one, still running.
        assert _running(name) == 1
        assert pc.is_persistent_running(pid)
    finally:
        pc.remove_container(pid, force=True)
