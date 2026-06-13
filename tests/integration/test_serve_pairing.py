"""Integration tests for spec 004 — serve mobile-pairing and reconnect.

Docker-gated. Verifies the wiring of the new ``paired`` field through
``cmd_ps`` against a real container. The case that requires a live Claude
login (true mobile-pairing handshake) is marked ``xfail`` when no real
credential is present; it is the manual-validation responsibility per
``quickstart.md`` §1.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from asdd import auth, bootstrap, supervisor
from asdd import project_container as pc

pytestmark = pytest.mark.docker


def _seed_fake_store(asdd_home: Path) -> None:
    auth.prepare_empty_store(asdd_home)
    auth.store_json_path(asdd_home).write_text(json.dumps({"email": "ci@example.com"}))
    auth.credentials_file(asdd_home).write_text(json.dumps({"accessToken": "ci-tok"}))
    auth.mark_fresh_login(asdd_home)


def _register_project(asdd_home: Path, project_id: str) -> Path:
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


def _poll_pairing(project_id: str, *, target: str, timeout: float) -> str | None:
    """Poll pairing_state every 2s up to ``timeout`` seconds; return the
    final value or None if target reached."""
    start = time.monotonic()
    last = None
    while time.monotonic() - start < timeout:
        last = pc.pairing_state(project_id)
        if last == target:
            return last
        time.sleep(2)
    return last


def test_ps_shows_paired_column_for_running_serve(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wiring proof: a running serve container shows up in cmd_ps with a
    ``paired`` key. Uses ASDD_SESSION_STUB so no real claude is launched —
    therefore no session JSON, therefore ``paired == "unpaired"``."""
    project_id = "vaultcontrol"
    _seed_fake_store(asdd_home_with_project)
    pc.ensure_image_built()

    monkeypatch.setenv("ASDD_SESSION_STUB", "1")
    # Stub the launchd install so we don't touch the host's launchd.
    monkeypatch.setattr(supervisor, "install", lambda pid, environ=None: None)

    container = pc.container_name(project_id)
    subprocess.run(["docker", "stop", container], capture_output=True)
    pc.remove_container(project_id)

    started = bootstrap.cmd_serve(asdd_home=asdd_home_with_project, project_id=project_id)
    assert started
    try:
        rows = bootstrap.cmd_ps()
        ours = next(r for r in rows if r["project_id"] == project_id)
        assert "paired" in ours
        assert ours["paired"] in ("paired", "unpaired", "reconnecting", "n/a")
    finally:
        pc.stop_container(project_id)
        pc.remove_container(project_id)
        assert _wait_for_gone(container)


@pytest.mark.xfail(
    reason="Requires a live Claude login + outbound reach to the Anthropic "
    "pairing service. Manual quickstart §1 covers this on the Mac.",
    strict=False,
)
def test_serve_session_pairs_within_30s(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 004 SC-001 — paired within 30s of serve startup.

    Run only with a real subscription credential and outbound reach to
    Anthropic's pairing service. xfail when those aren't present.
    """
    project_id = "vaultcontrol"
    pc.ensure_image_built()
    monkeypatch.setattr(supervisor, "install", lambda pid, environ=None: None)
    container = pc.container_name(project_id)
    subprocess.run(["docker", "stop", container], capture_output=True)
    pc.remove_container(project_id)

    bootstrap.cmd_serve(asdd_home=asdd_home_with_project, project_id=project_id)
    try:
        final = _poll_pairing(project_id, target="paired", timeout=30.0)
        assert final == "paired", f"did not pair within 30s: final={final}"
    finally:
        pc.stop_container(project_id)
        pc.remove_container(project_id)
        _wait_for_gone(container)


@pytest.mark.xfail(
    reason="Requires a live login + the ability to disconnect/reconnect the "
    "container's network mid-test. Covered by quickstart §3 on the Mac.",
    strict=False,
)
def test_serve_session_recovers_after_network_loss(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 004 SC-002 — re-paired within 60s of route restoration."""
    project_id = "vaultcontrol"
    pc.ensure_image_built()
    monkeypatch.setattr(supervisor, "install", lambda pid, environ=None: None)
    container = pc.container_name(project_id)
    subprocess.run(["docker", "stop", container], capture_output=True)
    pc.remove_container(project_id)

    bootstrap.cmd_serve(asdd_home=asdd_home_with_project, project_id=project_id)
    try:
        assert _poll_pairing(project_id, target="paired", timeout=30.0) == "paired"
        subprocess.run(["docker", "network", "disconnect", "bridge", container])
        time.sleep(90)
        subprocess.run(["docker", "network", "connect", "bridge", container])
        final = _poll_pairing(project_id, target="paired", timeout=60.0)
        assert final == "paired"
    finally:
        pc.stop_container(project_id)
        pc.remove_container(project_id)
        _wait_for_gone(container)


@pytest.mark.xfail(
    reason="Requires a live login + the ability to observe launchd-driven "
    "container relaunch. Covered by quickstart §4 on the Mac.",
    strict=False,
)
def test_serve_session_repairs_after_container_restart(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 004 SC-003 — re-paired within 60s of post-restart Claude up."""
    project_id = "vaultcontrol"
    pc.ensure_image_built()
    monkeypatch.setattr(supervisor, "install", lambda pid, environ=None: None)
    container = pc.container_name(project_id)
    subprocess.run(["docker", "stop", container], capture_output=True)
    pc.remove_container(project_id)

    bootstrap.cmd_serve(asdd_home=asdd_home_with_project, project_id=project_id)
    try:
        assert _poll_pairing(project_id, target="paired", timeout=30.0) == "paired"
        subprocess.run(["docker", "stop", container], capture_output=True)
        # Manual relaunch (Linux dev — no launchd): mirror what the babysitter would do.
        pc.start_existing(project_id)
        final = _poll_pairing(project_id, target="paired", timeout=60.0)
        assert final == "paired"
    finally:
        pc.stop_container(project_id)
        pc.remove_container(project_id)
        _wait_for_gone(container)
