"""Unit tests for asdd/registry.py and asdd/registry_reload.py (T025).

Covers: schema validation, cross-row invariants, mtime hot-reload,
graceful failure-with-prior-good-copy.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from asdd._schemas import RegistryLoadError
from asdd.registry import Registry, active_projects, find, load
from asdd.registry_reload import RegistryWatcher

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_load_empty_registry(tmp_path: Path) -> None:
    src = FIXTURES / "projects.yml.valid" / "empty.yml"
    dest = tmp_path / "projects.yml"
    shutil.copy(src, dest)
    reg = load(dest)
    assert reg.version == 1
    assert reg.default_project_id == "vaultcontrol"
    assert reg.projects == ()


def test_load_three_project_mixed_states(tmp_path: Path) -> None:
    src = FIXTURES / "projects.yml.valid" / "three-projects-mixed-states.yml"
    dest = tmp_path / "projects.yml"
    shutil.copy(src, dest)
    reg = load(dest)
    assert len(reg.projects) == 3
    assert {p.id for p in reg.projects} == {"vaultcontrol", "acme-unity", "old-experiment"}
    assert {p.lifecycle_state for p in reg.projects} == {"active", "paused", "archived"}

    # active_projects returns exactly one
    actives = active_projects(reg)
    assert len(actives) == 1
    assert actives[0].id == "vaultcontrol"

    # find resolves both hits and misses
    assert find(reg, "acme-unity").lifecycle_state == "paused"
    assert find(reg, "does-not-exist") is None


@pytest.mark.parametrize(
    "fixture_name",
    [
        "missing-default-id.yml",
        "bad-id-regex.yml",
        "malformed.yml",
        "wrong-version.yml",
    ],
)
def test_load_rejects_invalid_fixtures(tmp_path: Path, fixture_name: str) -> None:
    src = FIXTURES / "projects.yml.invalid" / fixture_name
    dest = tmp_path / "projects.yml"
    shutil.copy(src, dest)
    with pytest.raises(RegistryLoadError):
        load(dest)


def test_load_rejects_duplicate_id(tmp_path: Path) -> None:
    p = tmp_path / "projects.yml"
    p.write_text("""version: 1
default_project_id: vaultcontrol
projects:
  - id: dup
    name: One
    workspace_path: /tmp/one
    default_branch: main
    lifecycle_state: active
    created_at: 2026-05-14T00:00:00Z
    last_checked_at: 2026-05-14T00:00:00Z
  - id: dup
    name: Two
    workspace_path: /tmp/two
    default_branch: main
    lifecycle_state: active
    created_at: 2026-05-14T00:00:00Z
    last_checked_at: 2026-05-14T00:00:00Z
""")
    with pytest.raises(RegistryLoadError, match="duplicate ids"):
        load(p)


def test_load_rejects_duplicate_workspace_path(tmp_path: Path) -> None:
    p = tmp_path / "projects.yml"
    p.write_text("""version: 1
default_project_id: vaultcontrol
projects:
  - id: aa
    name: A
    workspace_path: /tmp/shared
    default_branch: main
    lifecycle_state: active
    created_at: 2026-05-14T00:00:00Z
    last_checked_at: 2026-05-14T00:00:00Z
  - id: bb
    name: B
    workspace_path: /tmp/shared
    default_branch: main
    lifecycle_state: active
    created_at: 2026-05-14T00:00:00Z
    last_checked_at: 2026-05-14T00:00:00Z
""")
    with pytest.raises(RegistryLoadError, match="duplicate workspace_path"):
        load(p)


def test_watcher_hot_reload_on_mtime_change(tmp_path: Path) -> None:
    asdd_home = tmp_path / "asdd_home"
    (asdd_home / "_state").mkdir(parents=True)
    reg_path = asdd_home / "_state" / "projects.yml"
    shutil.copy(FIXTURES / "projects.yml.valid" / "empty.yml", reg_path)

    watcher = RegistryWatcher(reg_path, asdd_home=asdd_home)
    assert len(watcher.current().projects) == 0

    # Replace with a multi-project version and bump mtime
    shutil.copy(FIXTURES / "projects.yml.valid" / "three-projects-mixed-states.yml", reg_path)
    # Ensure mtime ticks even on filesystems with second-resolution mtimes.
    new_mtime = time.time() + 2
    import os

    os.utime(reg_path, (new_mtime, new_mtime))

    reloaded = watcher.reload_if_changed()
    assert len(reloaded.projects) == 3


def test_watcher_keeps_prior_good_on_bad_reload(tmp_path: Path) -> None:
    asdd_home = tmp_path / "asdd_home"
    (asdd_home / "_state").mkdir(parents=True)
    reg_path = asdd_home / "_state" / "projects.yml"
    shutil.copy(FIXTURES / "projects.yml.valid" / "one-project.yml", reg_path)

    watcher = RegistryWatcher(reg_path, asdd_home=asdd_home)
    good = watcher.current()
    assert len(good.projects) == 1

    # Corrupt the file
    shutil.copy(FIXTURES / "projects.yml.invalid" / "malformed.yml", reg_path)
    import os

    bumped = time.time() + 2
    os.utime(reg_path, (bumped, bumped))

    still_good = watcher.reload_if_changed()
    assert still_good is good  # same object, prior copy retained

    # Audit log row was emitted
    audit_path = asdd_home / "_state" / "audit.log"
    assert audit_path.exists()
    content = audit_path.read_text().strip().splitlines()
    assert len(content) == 1
    assert '"kind":"registry_load_error"' in content[0]


def test_registry_dataclass_is_frozen() -> None:
    reg = Registry(version=1, default_project_id="x", projects=())
    with pytest.raises(Exception):  # noqa: B017 — FrozenInstanceError or AttributeError
        reg.version = 2  # type: ignore[misc]
