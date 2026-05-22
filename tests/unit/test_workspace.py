"""Unit tests for project workspace scaffolding helpers."""

from __future__ import annotations

from pathlib import Path

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
