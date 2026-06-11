"""CLI surface tests for `asdd open` and `asdd claude` (feature 001).

The handlers (`cmd_open`, `cmd_claude`) are monkeypatched so we exercise the
Click wiring — argument parsing, error translation, exit codes — without
touching Docker.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from asdd import bootstrap
from asdd import project_container as pc


@pytest.fixture
def runner() -> CliRunner:
    # Click 8.4 dropped `mix_stderr=False`; stderr is always captured
    # separately on `result.stderr` now.
    return CliRunner()


def _redirect_asdd_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    """Force `_asdd_home_from_env()` to return our tmp_path home so the
    CLI handler doesn't read the real environment."""
    monkeypatch.setattr(bootstrap, "_asdd_home_from_env", lambda: home)


# --- asdd claude -----------------------------------------------------------


def test_cli_claude_happy_path(
    runner: CliRunner, asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Click invokes cmd_claude with the project id and exits with its rc."""
    _redirect_asdd_home(monkeypatch, asdd_home_with_project)
    called: dict[str, object] = {}

    def fake_cmd_claude(*, asdd_home: Path, project_id: str) -> int:
        called["asdd_home"] = asdd_home
        called["project_id"] = project_id
        return 0

    monkeypatch.setattr(bootstrap, "cmd_claude", fake_cmd_claude)
    result = runner.invoke(bootstrap.cli, ["claude", "vaultcontrol"])
    assert result.exit_code == 0
    assert called == {"asdd_home": asdd_home_with_project, "project_id": "vaultcontrol"}


def test_cli_claude_translates_bootstrap_error(
    runner: CliRunner, asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `BootstrapError` from cmd_claude becomes exit 1 with the message on stderr."""
    _redirect_asdd_home(monkeypatch, asdd_home_with_project)

    def boom(**_: object) -> int:
        raise bootstrap.BootstrapError("no subscription login")

    monkeypatch.setattr(bootstrap, "cmd_claude", boom)
    result = runner.invoke(bootstrap.cli, ["claude", "vaultcontrol"])
    assert result.exit_code == 1
    assert "no subscription login" in result.stderr


def test_cli_claude_translates_already_running(
    runner: CliRunner, asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`AlreadyRunningError` (e.g. an interactive container is already up)
    becomes exit 1 and the helpful message reaches the operator."""
    _redirect_asdd_home(monkeypatch, asdd_home_with_project)

    def boom(**_: object) -> int:
        raise pc.AlreadyRunningError("vaultcontrol", mode="interactive")

    monkeypatch.setattr(bootstrap, "cmd_claude", boom)
    result = runner.invoke(bootstrap.cli, ["claude", "vaultcontrol"])
    assert result.exit_code == 1
    assert "already open" in result.stderr


def test_cli_claude_command_help_mentions_claude(runner: CliRunner) -> None:
    """The command help text states this command starts Claude."""
    result = runner.invoke(bootstrap.cli, ["claude", "--help"])
    assert result.exit_code == 0
    assert "Claude" in result.output


# --- asdd open contract regression -----------------------------------------


def test_cli_open_help_does_not_advertise_claude(runner: CliRunner) -> None:
    """Feature 001 US1 + FR-013: the help text must say `asdd open` lands in
    a shell, not Claude. This is a contract regression guard."""
    result = runner.invoke(bootstrap.cli, ["open", "--help"])
    assert result.exit_code == 0
    text = result.output
    assert "bash shell" in text or "shell" in text
    # The phrasing "no Claude" appears in the help so a future change can't
    # silently flip the contract without this test screaming.
    assert "no Claude" in text or "no claude" in text.lower()
