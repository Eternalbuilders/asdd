"""Spec 004 T006 — asdd ps PAIRED column tests.

Mocks ``project_container.list_running`` so we test the CLI rendering and
the data-flow of the new ``paired`` field without needing docker.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from asdd import bootstrap
from asdd import project_container as pc


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _row(project_id: str, mode: str, paired: str) -> dict[str, str]:
    return {
        "name": pc.container_name(project_id),
        "project_id": project_id,
        "mode": mode,
        "started_at": "2026-06-13T07:00:00Z",
        "paired": paired,
    }


def test_cli_ps_renders_paired_column(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ps renderer must surface the new PAIRED column header and value."""
    monkeypatch.setattr(
        pc,
        "list_running",
        lambda: [_row("hello-world", "persistent", "paired")],
    )
    result = runner.invoke(bootstrap.cli, ["ps"])
    assert result.exit_code == 0
    assert "PAIRED" in result.output
    assert "paired" in result.output
    assert "hello-world" in result.output


def test_cli_ps_renders_each_pairing_state(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        _row("a", "persistent", "paired"),
        _row("b", "persistent", "unpaired"),
        _row("c", "persistent", "reconnecting"),
        _row("d", "interactive", "n/a"),
    ]
    monkeypatch.setattr(pc, "list_running", lambda: rows)
    result = runner.invoke(bootstrap.cli, ["ps"])
    assert result.exit_code == 0
    for state in ("paired", "unpaired", "reconnecting", "n/a"):
        assert state in result.output, result.output


def test_cli_ps_no_containers_unchanged(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pc, "list_running", lambda: [])
    result = runner.invoke(bootstrap.cli, ["ps"])
    assert result.exit_code == 0
    assert "no project containers running" in result.output


def test_cmd_ps_returns_paired_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """The data layer (cmd_ps → list_running) carries the paired field through."""
    monkeypatch.setattr(
        pc, "list_running", lambda: [_row("p", "persistent", "reconnecting")]
    )
    rows = bootstrap.cmd_ps()
    assert rows == [_row("p", "persistent", "reconnecting")]
    assert rows[0]["paired"] == "reconnecting"
