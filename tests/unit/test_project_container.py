"""Unit tests for spec 009 changes to asdd.project_container.

Asserts the mount profile and the API-key gating with ``subprocess.run``
mocked — no docker required.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from asdd import auth
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


def test_auth_mounts_with_project_id_returns_three_tuples_in_order(tmp_path: Path) -> None:
    """Spec 003 / contracts/auth-mounts.md Case B: 3 tuples in the
    contractual order [claude.json, ~/.claude dir, ~/.claude/.credentials.json]."""
    home = tmp_path / "asdd-home"
    mounts = pc.auth_mounts(home, project_id="p")
    container_paths = [c for _, c, _ in mounts]
    assert container_paths == [
        f"{pc.IN_CONTAINER_USER_HOME}/.claude.json",
        f"{pc.IN_CONTAINER_USER_HOME}/.claude",
        f"{pc.IN_CONTAINER_USER_HOME}/.claude/.credentials.json",
    ]
    assert all(mode == "rw" for _, _, mode in mounts)


def test_auth_mounts_without_project_id_returns_two_shared_tuples(tmp_path: Path) -> None:
    """Spec 003 / contracts/auth-mounts.md Case A (throwaway login): only the
    two shared credential mounts, no ~/.claude directory mount."""
    home = tmp_path / "asdd-home"
    mounts = pc.auth_mounts(home, project_id=None)
    container_paths = [c for _, c, _ in mounts]
    assert container_paths == [
        f"{pc.IN_CONTAINER_USER_HOME}/.claude.json",
        f"{pc.IN_CONTAINER_USER_HOME}/.claude/.credentials.json",
    ]


def test_auth_mounts_threads_project_id_to_ensure_mountable(tmp_path: Path) -> None:
    """Side effect: per-project subtree materialised at 0700."""
    import stat as _stat

    home = tmp_path / "asdd-home"
    pc.auth_mounts(home, project_id="p")
    pp = auth.per_project_dir(home, "p")
    assert pp.is_dir()
    assert _stat.S_IMODE(pp.stat().st_mode) == 0o700


def test_auth_mounts_default_arg_is_none(tmp_path: Path) -> None:
    """The signature change must keep the no-project-id form callable as a
    positional. interactive_login_run uses this."""
    home = tmp_path / "asdd-home"
    mounts = pc.auth_mounts(home)
    assert len(mounts) == 2


def test_autonomous_mounts_includes_store_by_default(tmp_path: Path) -> None:
    mounts = pc.autonomous_mounts(tmp_path / "ws", tmp_path / "home", project_id="p")
    containers = {c for _, c, _ in mounts}
    assert f"{pc.IN_CONTAINER_USER_HOME}/.claude.json" in containers


def test_autonomous_mounts_excludes_store_on_api_key(tmp_path: Path) -> None:
    mounts = pc.autonomous_mounts(
        tmp_path / "ws", tmp_path / "home", project_id="p", use_api_key=True
    )
    containers = {c for _, c, _ in mounts}
    assert f"{pc.IN_CONTAINER_USER_HOME}/.claude.json" not in containers
    assert containers == {pc.IN_CONTAINER_WORKDIR}


def test_autonomous_mounts_forwards_project_id(tmp_path: Path) -> None:
    """The per-project subtree path must appear in the rendered mount list."""
    home = tmp_path / "home"
    mounts = pc.autonomous_mounts(tmp_path / "ws", home, project_id="p")
    hosts = [h for h, _, _ in mounts]
    assert str(auth.per_project_dir(home, "p")) in hosts


def test_interactive_mounts_forwards_project_id(tmp_path: Path) -> None:
    home = tmp_path / "home"
    mounts = pc.interactive_mounts(tmp_path / "ws", home, project_id="p")
    hosts = [h for h, _, _ in mounts]
    assert str(auth.per_project_dir(home, "p")) in hosts


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


# --- spec 003 US4: migration notice -----------------------------------------


def _setup_legacy_state(home: Path) -> None:
    """Reproduce the pre-spec-003 layout: mixed transcripts under shared store."""
    legacy_projects = auth.store_claude_dir(home) / "projects"
    legacy_projects.mkdir(parents=True, exist_ok=True)
    (legacy_projects / "-asdd-home").mkdir(exist_ok=True)
    (legacy_projects / "-asdd-home" / "leftover.jsonl").write_text("legacy\n")


def test_start_container_emits_migration_notice_on_first_run_with_legacy_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec 003 FR-009 / SC-005: first start_container with legacy state
    surfaces the one-line notice and writes the suppression marker."""
    _fake_run_capture(monkeypatch)
    home = tmp_path / "home"
    _setup_legacy_state(home)
    assert not auth.legacy_notice_marker(home).exists()

    obj = pc.ProjectContainer(
        project_id="p",
        mode="autonomous",
        workspace_path=tmp_path / "ws",
        asdd_home=home,
    )
    pc.start_container(obj)

    captured = capsys.readouterr()
    assert "legacy mixed Claude state" in captured.err
    assert auth.legacy_notice_marker(home).exists()


def test_start_container_does_not_re_emit_migration_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_run_capture(monkeypatch)
    home = tmp_path / "home"
    _setup_legacy_state(home)
    # Pre-create the marker — the operator has already been notified.
    auth.store_dir(home).mkdir(parents=True, exist_ok=True)
    auth.legacy_notice_marker(home).write_text("")

    obj = pc.ProjectContainer(
        project_id="p",
        mode="autonomous",
        workspace_path=tmp_path / "ws",
        asdd_home=home,
    )
    pc.start_container(obj)

    captured = capsys.readouterr()
    assert "legacy mixed Claude state" not in captured.err


def test_start_container_no_notice_on_clean_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_run_capture(monkeypatch)
    home = tmp_path / "home"
    # No legacy state, no marker.

    obj = pc.ProjectContainer(
        project_id="p",
        mode="autonomous",
        workspace_path=tmp_path / "ws",
        asdd_home=home,
    )
    pc.start_container(obj)

    captured = capsys.readouterr()
    assert "legacy mixed Claude state" not in captured.err
    assert not auth.legacy_notice_marker(home).exists()


def test_start_container_per_project_state_dir_mounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 003 FR-001 / R2: the per-project subtree is mounted at ~/.claude,
    and the shared .credentials.json file overlay appears AFTER it in argv so
    the kernel's VFS resolves the file path to the shared host file."""
    calls = _fake_run_capture(monkeypatch)
    home = tmp_path / "home"

    obj = pc.ProjectContainer(
        project_id="alpha",
        mode="autonomous",
        workspace_path=tmp_path / "ws",
        asdd_home=home,
    )
    pc.start_container(obj)

    argv = calls[0]
    vflags = _vflags(argv)
    per_project_arg = f"{auth.per_project_dir(home, 'alpha')}:{pc.IN_CONTAINER_USER_HOME}/.claude:rw"
    creds_arg = (
        f"{auth.credentials_file(home)}:{pc.IN_CONTAINER_USER_HOME}/.claude/.credentials.json:rw"
    )
    assert per_project_arg in vflags, "per-project state subtree not mounted at ~/.claude"
    assert creds_arg in vflags, "shared .credentials.json overlay missing"
    assert vflags.index(per_project_arg) < vflags.index(creds_arg), (
        "spec 003 R2: directory mount must precede the file overlay inside it"
    )


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
    # Main process is the tmux-held remote-control session, named by project.
    assert argv[-2:] == [pc.IMAGE_NAME, "asdd-session"]
    assert "ASDD_PROJECT_ID=p" in argv


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
        # Non-persistent containers stay warm; the caller execs into them.
        assert calls[0][-2:] == ["sleep", "infinity"]


def test_attach_session_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args, *a, **kw):  # noqa: ANN001, ANN002, ANN003
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    pc.attach_session("hello")
    # Re-attaches to the tmux-held remote-control session (not a fresh claude).
    assert calls[0] == [
        "docker",
        "exec",
        "-it",
        pc.container_name("hello"),
        "tmux",
        "attach",
        "-t",
        pc.SESSION_TMUX_NAME,
    ]


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


# --- feature 001: ASDD_PROJECT_ID plumbing + attach_claude ----------------


def test_start_container_plumbs_asdd_project_id_for_all_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Feature 001 FR-007/FR-008: ASDD_PROJECT_ID must reach the container
    in every mode so /etc/profile.d/asdd-prompt.sh can pick it up."""
    for mode in ("interactive", "autonomous", "persistent"):
        calls = _fake_run_capture(monkeypatch)
        obj = pc.ProjectContainer(
            project_id="my-app",
            mode=mode,
            workspace_path=tmp_path / "ws",
            asdd_home=tmp_path / "home",
        )
        pc.start_container(obj)
        assert "ASDD_PROJECT_ID=my-app" in _eflags(calls[0]), (
            f"ASDD_PROJECT_ID missing for mode={mode!r}"
        )


def test_attach_shell_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression for feature 001 US1: asdd open uses a shell, not claude."""
    calls: list[list[str]] = []

    def fake_run(args, *a, **kw):  # noqa: ANN001, ANN002, ANN003
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    pc.attach_shell("hello")
    assert calls[0] == [
        "docker",
        "exec",
        "-it",
        pc.container_name("hello"),
        "bash",
    ]


def test_attach_claude_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Feature 001 US2: attach_claude execs `claude` in the project container."""
    calls: list[list[str]] = []

    def fake_run(args, *a, **kw):  # noqa: ANN001, ANN002, ANN003
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    pc.attach_claude("hello")
    assert calls[0] == [
        "docker",
        "exec",
        "-it",
        pc.container_name("hello"),
        "claude",
    ]


# --- spec 004: pairing_state derivation -----------------------------------


def _fake_docker(monkeypatch: pytest.MonkeyPatch, **outputs: object) -> list[list[str]]:
    """Stub subprocess.run to drive the helpers used by pairing_state.

    ``outputs`` keys:
      - is_running: True/False (inspect format `{{.State.Running}}`)
      - running_mode: "persistent" or "" (inspect Config.Labels)
      - sessions_stdout: stdout for the `cat ~/.claude/sessions/*.json` exec

    Returns the list of captured argv lists for spying.
    """
    calls: list[list[str]] = []

    def fake_run(args, *a, **kw):  # noqa: ANN001, ANN002, ANN003
        calls.append(list(args))
        if args[:2] == ["docker", "ps"]:
            # is_running uses `docker ps --filter name=... --format {{.ID}}`.
            stdout = "abc123\n" if outputs.get("is_running") else ""
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")
        if args[:2] == ["docker", "inspect"]:
            fmt = args[args.index("--format") + 1]
            if "asdd.mode" in fmt:
                mode = outputs.get("running_mode", "")
                return subprocess.CompletedProcess(args, 0, stdout=f"{mode}\n", stderr="")
        if args[:2] == ["docker", "exec"] and "sh" in args:
            stdout = str(outputs.get("sessions_stdout", ""))
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    return calls


def test_pairing_state_no_container(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_docker(monkeypatch, is_running=False)
    assert pc.pairing_state("p") == "n/a"


def test_pairing_state_running_but_no_session_file(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_docker(
        monkeypatch, is_running=True, running_mode="persistent", sessions_stdout=""
    )
    assert pc.pairing_state("p") == "unpaired"


def test_pairing_state_session_without_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    sessions = json.dumps(
        {
            "pid": 13,
            "cwd": pc.IN_CONTAINER_WORKDIR,
            "kind": "interactive",
            "updatedAt": 1781340311823,
            "bridgeSessionId": "",
        }
    )
    _fake_docker(
        monkeypatch,
        is_running=True,
        running_mode="persistent",
        sessions_stdout=sessions,
    )
    # Even with fresh updatedAt, empty bridgeSessionId means unpaired.
    assert pc.pairing_state("p", now=1781340311.823) == "unpaired"


def test_pairing_state_paired_when_bridge_present_and_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    now_s = 1781340311.823
    sessions = json.dumps(
        {
            "pid": 13,
            "cwd": pc.IN_CONTAINER_WORKDIR,
            "kind": "interactive",
            "updatedAt": int(now_s * 1000) - 10_000,  # 10s old
            "bridgeSessionId": "session_abc123",
        }
    )
    _fake_docker(
        monkeypatch,
        is_running=True,
        running_mode="persistent",
        sessions_stdout=sessions,
    )
    assert pc.pairing_state("p", now=now_s) == "paired"


def test_pairing_state_reconnecting_when_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    now_s = 1781340311.823
    sessions = json.dumps(
        {
            "pid": 13,
            "cwd": pc.IN_CONTAINER_WORKDIR,
            "kind": "interactive",
            "updatedAt": int(now_s * 1000) - 120_000,  # 120s old > 60s window
            "bridgeSessionId": "session_abc123",
        }
    )
    _fake_docker(
        monkeypatch,
        is_running=True,
        running_mode="persistent",
        sessions_stdout=sessions,
    )
    assert pc.pairing_state("p", now=now_s) == "reconnecting"


def test_pairing_state_ignores_non_serve_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session whose cwd is NOT IN_CONTAINER_WORKDIR is not the serve session."""
    import json

    now_s = 1781340311.823
    # One session in /tmp (not the serve cwd) — should be ignored.
    other = json.dumps(
        {
            "pid": 99,
            "cwd": "/tmp",
            "kind": "interactive",
            "updatedAt": int(now_s * 1000) - 1_000,
            "bridgeSessionId": "session_other",
        }
    )
    _fake_docker(
        monkeypatch, is_running=True, running_mode="persistent", sessions_stdout=other
    )
    assert pc.pairing_state("p", now=now_s) == "unpaired"


def test_pairing_state_is_filesystem_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec 004 R1: pairing_state MUST NOT make a network call; only docker exec."""
    calls = _fake_docker(monkeypatch, is_running=True, running_mode="persistent")
    pc.pairing_state("p")
    # Every subprocess.run call must be a docker call. No curl, no python -m urllib, etc.
    for argv in calls:
        assert argv[0] == "docker", f"non-docker call observed: {argv}"
