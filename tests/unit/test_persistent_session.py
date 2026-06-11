"""Unit tests for spec 010 host-side command logic (no docker / no launchd).

The container and supervisor surfaces are mocked; these assert serve/attach/
stop behaviour and the FR-013 reuse wiring in dispatch/open.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from asdd import bootstrap, supervisor
from asdd import project_container as pc


def test_serve_requires_login(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pc, "is_persistent_running", lambda pid: False)
    with pytest.raises(bootstrap.BootstrapError, match="no subscription login"):
        bootstrap.cmd_serve(asdd_home=asdd_home_with_project, project_id="vaultcontrol")


def test_serve_noop_when_already_running(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pc, "is_persistent_running", lambda pid: True)
    # Must not touch docker/supervisor when already running.
    monkeypatch.setattr(pc, "ensure_image_built", lambda *a, **k: pytest.fail("started"))
    assert bootstrap.cmd_serve(asdd_home=asdd_home_with_project, project_id="vaultcontrol") is False


def test_attach_refuses_when_not_running(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pc, "is_persistent_running", lambda pid: False)
    with pytest.raises(bootstrap.BootstrapError, match="no persistent session running"):
        bootstrap.cmd_attach(asdd_home=asdd_home_with_project, project_id="vaultcontrol")


def test_stop_uninstalls_then_stops(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    monkeypatch.setattr(supervisor, "uninstall", lambda pid: order.append("uninstall"))
    monkeypatch.setattr(pc, "stop_container", lambda pid: order.append("stop") or True)
    monkeypatch.setattr(pc, "remove_container", lambda pid, **k: order.append("rm") or True)
    assert bootstrap.cmd_stop(asdd_home=asdd_home_with_project, project_id="vaultcontrol") is True
    # Supervisor disabled before the container is stopped (stop wins over relaunch).
    assert order == ["uninstall", "stop", "rm"]


def test_dispatch_reuses_persistent_container(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = asdd_home_with_project / "projects" / "vaultcontrol"
    (ws / "inbox").mkdir(parents=True, exist_ok=True)
    job = ws / "inbox" / "job.md"
    job.write_text("# job\n")

    monkeypatch.setattr(pc, "is_persistent_running", lambda pid: True)
    monkeypatch.setattr(pc, "ensure_image_built", lambda *a, **k: pytest.fail("should reuse"))
    monkeypatch.setattr(pc, "start_container", lambda *a, **k: pytest.fail("should reuse"))
    ran: list[str] = []
    monkeypatch.setattr(bootstrap, "_run_job_exec", lambda pid, path, rel: ran.append(pid))

    result = bootstrap.cmd_dispatch(
        asdd_home=asdd_home_with_project, project_id="vaultcontrol", job_path=job
    )
    assert ran == ["vaultcontrol"]
    assert result == ws / "results" / "job.result.md"


def test_open_side_execs_shell_when_persistent(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Feature 001 US1: ``asdd open`` is a shell, never Claude. When a
    persistent session is already running, the container exists and Claude
    is held inside tmux. We must side-exec a bash shell into the same
    container — the operator gets the shell they asked for, the persistent
    session keeps running. We must NOT start a new container, NOT attach to
    the tmux session (that would land in Claude), and NOT stop the container
    on exit (that would kill the persistent session)."""
    monkeypatch.setattr(pc, "is_persistent_running", lambda pid: True)
    monkeypatch.setattr(pc, "start_container", lambda *a, **k: pytest.fail("should not start"))
    monkeypatch.setattr(pc, "attach_session", lambda pid: pytest.fail("should not attach to tmux"))
    monkeypatch.setattr(pc, "stop_container", lambda pid: pytest.fail("must not stop persistent container"))

    attach_calls: list[str] = []

    def fake_attach_shell(pid: str) -> int:
        attach_calls.append(pid)
        return 0

    monkeypatch.setattr(pc, "attach_shell", fake_attach_shell)
    rc = bootstrap.cmd_open(asdd_home=asdd_home_with_project, project_id="vaultcontrol")
    assert rc == 0
    assert attach_calls == ["vaultcontrol"]


def test_claude_attaches_when_persistent(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Feature 001 US2 / FR-006: asdd claude re-attaches to a running
    persistent session via tmux, rather than starting a second Claude."""
    monkeypatch.setattr(pc, "is_persistent_running", lambda pid: True)
    monkeypatch.setattr(pc, "start_container", lambda *a, **k: pytest.fail("should attach"))
    monkeypatch.setattr(pc, "attach_session", lambda pid: 0)
    assert (
        bootstrap.cmd_claude(asdd_home=asdd_home_with_project, project_id="vaultcontrol")
        == 0
    )


def test_supervise_restarts_and_counts_when_down(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Babysitter: container down + exists → start_existing, bump count, wait."""
    events: list[str] = []
    monkeypatch.setattr(pc, "is_running", lambda pid: False)
    monkeypatch.setattr(pc, "exists", lambda pid: True)
    monkeypatch.setattr(pc, "start_existing", lambda pid: events.append("start_existing"))
    monkeypatch.setattr(pc, "wait_container", lambda pid: events.append("wait") or 137)

    rc = bootstrap.cmd_serve_supervise(
        asdd_home=asdd_home_with_project, project_id="vaultcontrol"
    )
    assert events == ["start_existing", "wait"]
    assert rc == 137
    assert bootstrap._read_restarts(asdd_home_with_project, "vaultcontrol") == 1


def test_supervise_just_waits_when_already_up(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Babysitter: container already up (e.g. just after serve) → no restart bump."""
    monkeypatch.setattr(pc, "is_running", lambda pid: True)
    monkeypatch.setattr(pc, "start_existing", lambda pid: pytest.fail("should not restart"))
    monkeypatch.setattr(pc, "wait_container", lambda pid: 0)
    bootstrap.cmd_serve_supervise(asdd_home=asdd_home_with_project, project_id="vaultcontrol")
    assert bootstrap._read_restarts(asdd_home_with_project, "vaultcontrol") == 0
