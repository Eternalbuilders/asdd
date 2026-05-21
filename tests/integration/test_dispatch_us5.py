"""Integration test for spec 008 Phase B — autonomous-mode dispatch (T126).

Asserts the FR-009 primitive: a non-operator caller can start a project's
container in autonomous mode, hand it a job-note, get a result on disk,
and the container stops cleanly. Auth comes from ANTHROPIC_API_KEY env
(not the operator's host ~/.claude/), and the integration test uses
ASDD_JOB_STUB_OUTPUT to avoid needing a live LLM call.

Gated by @pytest.mark.docker; skipped where no docker socket.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from asdd import bootstrap
from asdd import project_container as pc


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


@pytest.mark.docker
def test_dispatch_writes_result_and_stops_container(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: dispatch a job → result file appears → container is gone."""
    project_id = "vaultcontrol"
    container = pc.container_name(project_id)

    # Clean any stale container.
    subprocess.run(["docker", "stop", container], capture_output=True)

    workspace = asdd_home_with_project / "projects" / project_id
    inbox = workspace / "inbox"
    inbox.mkdir(exist_ok=True)
    job_path = inbox / "smoke-job.md"
    job_path.write_text("# job\n\nrun the smoke test\n")

    # Use the stub-output env var so the runner shim writes a deterministic
    # result without contacting Claude. start_container propagates this
    # var into the container (autonomous-mode passthrough).
    monkeypatch.setenv("ASDD_JOB_STUB_OUTPUT", "stub-result-for-smoke")
    # Provide a stub API key so the env-var passthrough seam exercises both
    # vars at once (the runner shim ignores it under stub mode).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "stub-key-not-used")

    pc.ensure_image_built()
    result_path = bootstrap.cmd_dispatch(
        asdd_home=asdd_home_with_project,
        project_id=project_id,
        job_path=job_path,
    )

    assert result_path.is_file(), f"result file missing at {result_path}"
    assert result_path.read_text().strip() == "stub-result-for-smoke"
    assert _wait_for_gone(container), "container did not shut down after dispatch"


def test_dispatch_refuses_job_outside_workspace(
    asdd_home_with_project: Path, tmp_path: Path
) -> None:
    """A job-note outside the project's workspace fails fast (no mount = unreachable)."""
    rogue = tmp_path / "rogue-job.md"
    rogue.write_text("# rogue\n")
    with pytest.raises(bootstrap.BootstrapError, match="not under project workspace"):
        bootstrap.cmd_dispatch(
            asdd_home=asdd_home_with_project,
            project_id="vaultcontrol",
            job_path=rogue,
        )


def test_dispatch_refuses_missing_job_file(asdd_home_with_project: Path) -> None:
    """A non-existent job-note path is rejected before any container starts."""
    ws = asdd_home_with_project / "projects" / "vaultcontrol"
    missing = ws / "inbox" / "does-not-exist.md"
    with pytest.raises(bootstrap.BootstrapError, match="job-note not found"):
        bootstrap.cmd_dispatch(
            asdd_home=asdd_home_with_project,
            project_id="vaultcontrol",
            job_path=missing,
        )
