"""Unit tests for spec 009 changes to asdd.project_container.

Asserts the mount profile and the API-key gating with ``subprocess.run``
mocked — no docker required.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from asdd import project_container as pc


def _fake_run_capture(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Patch subprocess.run inside project_container to capture argv and
    return a successful `docker run` result."""
    calls: list[list[str]] = []

    def fake_run(args, *a, **kw):  # noqa: ANN001, ANN002, ANN003
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout="container-id\n", stderr="")

    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    return calls


def _vflags(argv: list[str]) -> list[str]:
    return [argv[i + 1] for i, tok in enumerate(argv) if tok == "-v"]


def _eflags(argv: list[str]) -> list[str]:
    return [argv[i + 1] for i, tok in enumerate(argv) if tok == "-e"]


# --- mount helpers ---------------------------------------------------------


def test_auth_mounts_maps_store_to_user_home(tmp_path: Path) -> None:
    mounts = pc.auth_mounts(tmp_path / "asdd-home")
    containers = {c for _, c, _ in mounts}
    assert f"{pc.IN_CONTAINER_USER_HOME}/.claude.json" in containers
    assert f"{pc.IN_CONTAINER_USER_HOME}/.claude" in containers
    assert all(mode == "rw" for _, _, mode in mounts)


def test_autonomous_mounts_includes_store_by_default(tmp_path: Path) -> None:
    mounts = pc.autonomous_mounts(tmp_path / "ws", tmp_path / "home")
    containers = {c for _, c, _ in mounts}
    assert f"{pc.IN_CONTAINER_USER_HOME}/.claude.json" in containers


def test_autonomous_mounts_excludes_store_on_api_key(tmp_path: Path) -> None:
    mounts = pc.autonomous_mounts(tmp_path / "ws", tmp_path / "home", use_api_key=True)
    containers = {c for _, c, _ in mounts}
    assert f"{pc.IN_CONTAINER_USER_HOME}/.claude.json" not in containers
    assert containers == {pc.IN_CONTAINER_WORKDIR}


# --- start_container argv shape --------------------------------------------


def test_start_container_subscription_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default autonomous run mounts the store and injects no API key."""
    calls = _fake_run_capture(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-be-injected")

    obj = pc.ProjectContainer(
        project_id="p",
        mode="autonomous",
        workspace_path=tmp_path / "ws",
        asdd_home=tmp_path / "home",
    )
    pc.start_container(obj)

    argv = calls[0]
    assert any(".claude.json" in v for v in _vflags(argv)), "store not mounted"
    assert not any(e.startswith("ANTHROPIC_API_KEY=") for e in _eflags(argv))


def test_start_container_api_key_optin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """API-key opt-in injects the key and suppresses the store mount."""
    calls = _fake_run_capture(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

    obj = pc.ProjectContainer(
        project_id="p",
        mode="autonomous",
        workspace_path=tmp_path / "ws",
        asdd_home=tmp_path / "home",
        use_api_key=True,
    )
    pc.start_container(obj)

    argv = calls[0]
    assert not any(".claude.json" in v for v in _vflags(argv)), "store should be suppressed"
    assert "ANTHROPIC_API_KEY=sk-test-key" in _eflags(argv)


def test_start_container_interactive_mounts_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_run_capture(monkeypatch)
    obj = pc.ProjectContainer(
        project_id="p",
        mode="interactive",
        workspace_path=tmp_path / "ws",
        asdd_home=tmp_path / "home",
    )
    pc.start_container(obj)
    assert any(".claude.json" in v for v in _vflags(calls[0]))


def test_start_container_stub_output_always_propagated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fake_run_capture(monkeypatch)
    monkeypatch.setenv("ASDD_JOB_STUB_OUTPUT", "canned")
    obj = pc.ProjectContainer(
        project_id="p",
        mode="autonomous",
        workspace_path=tmp_path / "ws",
        asdd_home=tmp_path / "home",
    )
    pc.start_container(obj)
    assert "ASDD_JOB_STUB_OUTPUT=canned" in _eflags(calls[0])


# --- spec 010: persistent mode --------------------------------------------


def test_persistent_start_omits_rm_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Persistent containers persist (no --rm) and are NOT managed by a Docker
    # restart policy — the launchd babysitter owns their lifecycle.
    calls = _fake_run_capture(monkeypatch)
    obj = pc.ProjectContainer(
        project_id="p",
        mode="persistent",
        workspace_path=tmp_path / "ws",
        asdd_home=tmp_path / "home",
    )
    pc.start_container(obj)
    argv = calls[0]
    assert "--rm" not in argv
    assert "--restart" not in argv


def test_wait_and_start_existing_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args, *a, **kw):  # noqa: ANN001, ANN002, ANN003
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout="0\n", stderr="")

    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    pc.start_existing("hello")
    assert calls[-1] == ["docker", "start", pc.container_name("hello")]
    assert pc.wait_container("hello") == 0
    assert calls[-1] == ["docker", "wait", pc.container_name("hello")]


def test_interactive_and_autonomous_still_use_rm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for mode in ("interactive", "autonomous"):
        calls = _fake_run_capture(monkeypatch)
        obj = pc.ProjectContainer(
            project_id="p", mode=mode, workspace_path=tmp_path / "ws", asdd_home=tmp_path / "h"
        )
        pc.start_container(obj)
        assert "--rm" in calls[0]
        assert "--restart" not in calls[0]


def test_attach_session_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args, *a, **kw):  # noqa: ANN001, ANN002, ANN003
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    pc.attach_session("hello")
    assert calls[0] == ["docker", "exec", "-it", pc.container_name("hello"), "claude", "--continue"]


def test_restart_count_and_state_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args, *a, **kw):  # noqa: ANN001, ANN002, ANN003
        fmt = args[args.index("--format") + 1]
        out = "3" if "RestartCount" in fmt else "running"
        return subprocess.CompletedProcess(args, 0, stdout=out + "\n", stderr="")

    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    assert pc.restart_count("hello") == 3
    assert pc.state("hello") == "running"


def test_is_persistent_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pc, "is_running", lambda pid: True)
    monkeypatch.setattr(pc, "running_mode", lambda pid: "persistent")
    assert pc.is_persistent_running("hello") is True
    monkeypatch.setattr(pc, "running_mode", lambda pid: "interactive")
    assert pc.is_persistent_running("hello") is False
