"""Unit tests for the launchd supervisor (spec 010).

Pure-Python: plist generation, label/path, install/uninstall argv with
launchctl and the filesystem mocked/redirected. No launchd needed.
"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

import pytest

from asdd import supervisor


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_label_and_path(home: Path) -> None:
    assert supervisor.agent_label("hello") == "com.asdd.session.hello"
    assert supervisor.agent_path("hello") == (
        home / "Library" / "LaunchAgents" / "com.asdd.session.hello.plist"
    )


def test_render_plist_content(home: Path) -> None:
    raw = supervisor.render_plist(
        "hello", program_args=["/usr/bin/asdd", "serve", "hello", "--supervise"]
    )
    plist = plistlib.loads(raw)
    assert plist["Label"] == "com.asdd.session.hello"
    assert plist["ProgramArguments"] == ["/usr/bin/asdd", "serve", "hello", "--supervise"]
    assert plist["RunAtLoad"] is True
    # KeepAlive=True: the agent IS the supervisor (relaunches the babysitter).
    assert plist["KeepAlive"] is True
    assert plist["ThrottleInterval"] == supervisor.THROTTLE_INTERVAL
    # Log file routes babysitter output for diagnostics.
    assert "StandardOutPath" in plist
    assert "StandardErrorPath" in plist
    assert plist["StandardOutPath"] == plist["StandardErrorPath"]


def test_render_plist_pins_environment() -> None:
    raw = supervisor.render_plist(
        "hello",
        program_args=["/usr/bin/asdd", "serve", "hello", "--supervise"],
        environ={"ASDD_HOME": "/Users/m/Code/asdd"},
    )
    plist = plistlib.loads(raw)
    assert plist["EnvironmentVariables"] == {"ASDD_HOME": "/Users/m/Code/asdd"}


def test_asdd_program_args_supervise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor.shutil, "which", lambda _: "/usr/local/bin/asdd")
    assert supervisor.asdd_program_args("hello") == [
        "/usr/local/bin/asdd",
        "serve",
        "hello",
        "--supervise",
    ]


def test_install_writes_plist_and_loads(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args, *a, **kw):  # noqa: ANN001, ANN002, ANN003
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(supervisor.subprocess, "run", fake_run)
    path = supervisor.install("hello", program_args=["/usr/bin/asdd", "serve", "hello"])

    assert path.is_file()
    assert supervisor.is_installed("hello") is True
    # bootout (clean stale) then bootstrap the agent.
    assert any(c[:2] == ["launchctl", "bootout"] for c in calls)
    assert any(c[:2] == ["launchctl", "bootstrap"] for c in calls)


def test_uninstall_removes_plist(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        supervisor.subprocess,
        "run",
        lambda args, *a, **kw: subprocess.CompletedProcess(args, 0, stdout="", stderr=""),
    )
    supervisor.install("hello", program_args=["/usr/bin/asdd", "serve", "hello"])
    assert supervisor.uninstall("hello") is True
    assert supervisor.is_installed("hello") is False
    # idempotent when already gone
    assert supervisor.uninstall("hello") is False


def test_install_falls_back_to_load_on_bootstrap_failure(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(args, *a, **kw):  # noqa: ANN001, ANN002, ANN003
        calls.append(list(args))
        # bootstrap fails → triggers the `load -w` fallback path.
        rc = 1 if args[:2] == ["launchctl", "bootstrap"] else 0
        return subprocess.CompletedProcess(args, rc, stdout="", stderr="boom" if rc else "")

    monkeypatch.setattr(supervisor.subprocess, "run", fake_run)
    supervisor.install("hello", program_args=["/usr/bin/asdd", "serve", "hello"])
    assert any(c[:2] == ["launchctl", "load"] for c in calls)
