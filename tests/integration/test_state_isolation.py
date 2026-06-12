"""Integration tests for spec 003 — per-project Claude state isolation.

Two distinct project containers, real Docker daemon. The first test proves
US1 (no leakage of per-project state across containers); the second proves
US2 (shared credential file visible identically in both).

Gated by @pytest.mark.docker; skipped where no docker socket. Uses a seeded
credential store and short-lived containers; no live Claude call required.
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


def _register_project(asdd_home: Path, project_id: str) -> Path:
    """Add a project row to the registry and create its workspace dir."""
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
    return workspace


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


def _start(project_id: str, workspace: Path, asdd_home: Path) -> None:
    obj = pc.ProjectContainer(
        project_id=project_id,
        mode="interactive",
        workspace_path=workspace,
        asdd_home=asdd_home,
    )
    pc.start_container(obj)


def _exec(container: str, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "exec", container, *argv],
        capture_output=True,
        text=True,
    )


def test_two_projects_dont_see_each_others_per_project_state(
    asdd_home: Path,
) -> None:
    """Spec 003 FR-001 / SC-001 / US1: project A writes a sentinel under
    ~/.claude/projects/<slug>/; project B does not see it."""
    a_id, b_id = "iso-a", "iso-b"
    a_ws = _register_project(asdd_home, a_id)
    b_ws = _register_project(asdd_home, b_id)
    _seed_fake_store(asdd_home)
    pc.ensure_image_built()

    a_container = pc.container_name(a_id)
    b_container = pc.container_name(b_id)
    subprocess.run(["docker", "stop", a_container], capture_output=True)
    subprocess.run(["docker", "stop", b_container], capture_output=True)

    try:
        # Project A writes a sentinel into its per-project state.
        _start(a_id, a_ws, asdd_home)
        rc = _exec(
            a_container,
            "bash",
            "-c",
            "mkdir -p ~/.claude/projects/-asdd-home && "
            "echo from-a > ~/.claude/projects/-asdd-home/sentinel-a.txt",
        )
        assert rc.returncode == 0, rc.stderr

        # Project B sees nothing from A.
        _start(b_id, b_ws, asdd_home)
        out = _exec(
            b_container,
            "bash",
            "-c",
            "ls ~/.claude/projects/-asdd-home/ 2>/dev/null || echo EMPTY",
        )
        assert "sentinel-a.txt" not in out.stdout, (
            f"A's sentinel visible in B: {out.stdout!r}"
        )

        # Project B writes its own; confirm A still doesn't see it.
        _exec(
            b_container,
            "bash",
            "-c",
            "mkdir -p ~/.claude/projects/-asdd-home && "
            "echo from-b > ~/.claude/projects/-asdd-home/sentinel-b.txt",
        )
        out_a = _exec(
            a_container,
            "bash",
            "-c",
            "ls ~/.claude/projects/-asdd-home/",
        )
        assert "sentinel-a.txt" in out_a.stdout
        assert "sentinel-b.txt" not in out_a.stdout, (
            f"B's sentinel visible in A: {out_a.stdout!r}"
        )
    finally:
        pc.stop_container(a_id)
        pc.stop_container(b_id)


def test_shared_credentials_visible_in_both_projects(asdd_home: Path) -> None:
    """Spec 003 FR-002 / SC-002 / US2: both containers see the same
    .credentials.json content from the shared host file."""
    a_id, b_id = "shared-a", "shared-b"
    a_ws = _register_project(asdd_home, a_id)
    b_ws = _register_project(asdd_home, b_id)
    _seed_fake_store(asdd_home)
    pc.ensure_image_built()

    # Write a distinctive sentinel into the shared credential file on the host.
    sentinel = json.dumps({"accessToken": "shared-sentinel-xyz"})
    auth.credentials_file(asdd_home).write_text(sentinel)

    a_container = pc.container_name(a_id)
    b_container = pc.container_name(b_id)
    subprocess.run(["docker", "stop", a_container], capture_output=True)
    subprocess.run(["docker", "stop", b_container], capture_output=True)

    try:
        _start(a_id, a_ws, asdd_home)
        _start(b_id, b_ws, asdd_home)

        out_a = _exec(a_container, "cat", "/home/asdd/.claude/.credentials.json")
        out_b = _exec(b_container, "cat", "/home/asdd/.claude/.credentials.json")
        assert out_a.returncode == 0 and out_b.returncode == 0
        assert out_a.stdout == sentinel == out_b.stdout, (
            f"credential content diverged: a={out_a.stdout!r} b={out_b.stdout!r}"
        )

        # Token-refresh-like rewrite from project A's container; project B
        # picks it up on next start (well, immediately — same host file).
        refreshed = json.dumps({"accessToken": "refreshed-by-a"})
        rc = _exec(
            a_container,
            "bash",
            "-c",
            f"echo -n {refreshed!r} > /home/asdd/.claude/.credentials.json",
        )
        assert rc.returncode == 0, rc.stderr

        out_b2 = _exec(b_container, "cat", "/home/asdd/.claude/.credentials.json")
        assert out_b2.stdout == refreshed, (
            f"B did not see A's refresh: {out_b2.stdout!r}"
        )
    finally:
        pc.stop_container(a_id)
        pc.stop_container(b_id)
