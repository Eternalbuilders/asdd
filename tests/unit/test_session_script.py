"""Bash-level smoke for docker/files/asdd-session.sh outer role (spec 004 T005).

Stubs ``tmux`` on PATH with a logger so we can assert what argv the outer
role passes to it. Runs the outer role briefly with ``ASDD_PROJECT_ID=t``
and ``ASDD_SESSION_STUB=1`` so the inner role doesn't try to start claude.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_SCRIPT = REPO_ROOT / "docker" / "files" / "asdd-session.sh"
RUN_JOB_SCRIPT = REPO_ROOT / "docker" / "files" / "asdd-run-job.sh"


@pytest.fixture
def stubbed_tmux(tmp_path: Path) -> tuple[Path, Path]:
    """Write a tmux stub that logs argv and faux-implements the verbs the
    outer role uses. Returns (bin_dir, log_file).

    - ``new-session -d -s SESSION CMD`` returns 0 and never blocks.
    - ``attach -t SESSION -d`` returns 0 (logged), simulating the idle client.
    - ``has-session -t SESSION`` returns 0 once, then 1 to end the outer loop.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "tmux.log"
    state = tmp_path / "state"
    state.write_text("0")

    stub = bin_dir / "tmux"
    stub.write_text(
        f"""#!/usr/bin/env bash
echo "$@" >> {log}
case "$1" in
    new-session) exit 0 ;;
    attach) exit 0 ;;
    has-session)
        n=$(cat {state})
        echo $((n+1)) > {state}
        if [ "$n" -lt 1 ]; then exit 0; else exit 1; fi
        ;;
    *) exit 0 ;;
esac
"""
    )
    stub.chmod(0o755)
    return bin_dir, log


def _run_outer(bin_dir: Path, *, env_extra: dict[str, str] | None = None) -> int:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["ASDD_PROJECT_ID"] = "t"
    env["ASDD_SESSION_STUB"] = "1"
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        ["bash", str(SESSION_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.returncode


def test_outer_role_starts_detached_then_idle_attaches(stubbed_tmux: tuple[Path, Path]) -> None:
    """Spec 004 R2 / contracts/asdd-session.md: the outer role must
    ``tmux new-session -d`` and then ``tmux attach -d`` with the attach
    backgrounded so PID 1 stays the supervisor."""
    bin_dir, log = stubbed_tmux
    _run_outer(bin_dir)
    lines = log.read_text().strip().splitlines()
    # First call: new-session -d -s asdd <cmd>
    assert lines[0].startswith("new-session -d -s asdd "), lines
    # Second call: attach -t asdd -d (the idle client)
    attaches = [line for line in lines if line.startswith("attach ")]
    assert any("-t asdd -d" in a for a in attaches), lines


def test_outer_role_blocks_until_session_ends(stubbed_tmux: tuple[Path, Path]) -> None:
    """The outer role's `while has-session` loop must keep the script alive
    while the session exists and exit when it disappears."""
    bin_dir, log = stubbed_tmux
    start = time.monotonic()
    rc = _run_outer(bin_dir)
    elapsed = time.monotonic() - start
    # has-session was stubbed to return 0 once then 1, with a 5s sleep between.
    # So the script should exit within ~6s and return 0.
    assert rc == 0
    assert elapsed < 8.0, f"outer role hung: {elapsed:.1f}s"
    # has-session was called at least twice (loop iterations).
    has_session_calls = [
        line for line in log.read_text().splitlines() if line.startswith("has-session ")
    ]
    assert len(has_session_calls) >= 2


# --- spec 006: auto permission mode on every claude launch ----------------


def test_session_script_starts_claude_in_auto_mode() -> None:
    """Spec 006 / contracts/container-launch.md: BOTH claude invocations in
    asdd-session.sh (the --continue resume and the fresh-start fallback) must
    carry --permission-mode auto, or a resumed session silently reverts to
    prompting."""
    text = SESSION_SCRIPT.read_text()
    claude_lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip().startswith("claude ")
    ]
    assert claude_lines, "expected claude invocations in asdd-session.sh"
    for ln in claude_lines:
        assert "--permission-mode auto" in ln, ln
    # Specifically the resume and fresh-start calls.
    assert any("--continue" in ln and "--permission-mode auto" in ln for ln in claude_lines)
    assert any(
        "--continue" not in ln and "--permission-mode auto" in ln for ln in claude_lines
    )


def test_run_job_script_starts_claude_in_auto_mode() -> None:
    """Spec 006: the autonomous dispatch runner must start claude in auto mode."""
    text = RUN_JOB_SCRIPT.read_text()
    claude_lines = [
        ln.strip() for ln in text.splitlines() if ln.strip().startswith("claude ")
    ]
    assert claude_lines, "expected a claude invocation in asdd-run-job.sh"
    for ln in claude_lines:
        assert "--permission-mode auto" in ln, ln
        assert "--print" in ln, ln
