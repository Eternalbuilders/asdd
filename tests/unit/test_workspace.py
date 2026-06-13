"""Unit tests for project workspace scaffolding helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from asdd import workspace


def test_ensure_dir_creates_when_absent(tmp_path: Path) -> None:
    d = tmp_path / "specs"
    workspace._ensure_dir(d)
    assert d.is_dir()


def test_ensure_dir_noop_on_existing_dir(tmp_path: Path) -> None:
    d = tmp_path / "specs"
    d.mkdir()
    (d / "keep.md").write_text("x")
    workspace._ensure_dir(d)
    assert (d / "keep.md").read_text() == "x"  # untouched


def test_ensure_dir_replaces_dangling_symlink(tmp_path: Path) -> None:
    # The bug: a cloned repo's `specs` points at an external store missing on
    # this host. mkdir(exist_ok=True) used to raise FileExistsError here.
    link = tmp_path / "specs"
    link.symlink_to(tmp_path / "does-not-exist")
    assert link.is_symlink() and not link.exists()

    workspace._ensure_dir(link)

    assert link.is_dir()
    assert not link.is_symlink()


def test_ensure_dir_keeps_valid_symlink(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "specs"
    link.symlink_to(target)

    workspace._ensure_dir(link)

    # A symlink that resolves is the clone's choice — leave it intact.
    assert link.is_symlink()
    assert link.resolve() == target.resolve()


# --- spec 006: scaffold writes the Claude permission guardrails ------------


def _fake_templates_root(tmp_path: Path) -> Path:
    """A templates_root carrying the files scaffold() copies."""
    root = tmp_path / "_templates"
    (root / ".claude").mkdir(parents=True)
    (root / "constitution-starter.md").write_text("# constitution\n")
    (root / ".claude" / "settings.json").write_text(
        json.dumps({"permissions": {"deny": ["Bash(git push --force *)"]}}) + "\n"
    )
    return root


def test_scaffold_writes_claude_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """scaffold() must drop .claude/settings.json into the workspace, into the
    .claude/ dir that `specify init` creates — without clobbering it."""
    ws = tmp_path / "ws"

    def fake_init(workspace_path: Path) -> None:
        # Emulate `specify init`: create .specify/ and a pre-existing .claude/
        # dir with slash-command assets that must survive.
        (workspace_path / ".specify" / "memory").mkdir(parents=True)
        (workspace_path / ".claude" / "commands").mkdir(parents=True)
        (workspace_path / ".claude" / "commands" / "keep.md").write_text("keep")

    monkeypatch.setattr(workspace, "_run_specify_init", fake_init)

    workspace.scaffold(ws, templates_root=_fake_templates_root(tmp_path))

    settings = ws / ".claude" / "settings.json"
    assert settings.is_file()
    data = json.loads(settings.read_text())
    assert "Bash(git push --force *)" in data["permissions"]["deny"]
    # specify init's .claude/ assets are not clobbered.
    assert (ws / ".claude" / "commands" / "keep.md").read_text() == "keep"


def test_scaffold_raises_when_skeleton_settings_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"

    def fake_init(workspace_path: Path) -> None:
        (workspace_path / ".specify" / "memory").mkdir(parents=True)

    monkeypatch.setattr(workspace, "_run_specify_init", fake_init)

    root = tmp_path / "_templates"
    root.mkdir()
    (root / "constitution-starter.md").write_text("# constitution\n")
    # no .claude/settings.json on purpose

    with pytest.raises(FileNotFoundError, match="settings.json"):
        workspace.scaffold(ws, templates_root=root)
