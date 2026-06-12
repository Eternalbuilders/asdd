"""Unit tests for spec-002 bootstrap commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from asdd import bootstrap, project_container as pc, tool_manifest, tools as tools_mod


@pytest.fixture
def asdd_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a minimal $ASDD_HOME with one registered project."""
    home = tmp_path / "asdd"
    (home / "_state").mkdir(parents=True)
    (home / "templates").mkdir()
    workspace = home / "projects" / "dev"
    workspace.mkdir(parents=True)
    registry = {
        "version": 1,
        "projects": [
            {
                "id": "dev",
                "name": "dev",
                "description": "test",
                "workspace_path": str(workspace),
                "lifecycle_state": "active",
                "created_at": "2026-06-12T00:00:00Z",
            }
        ],
    }
    (home / "_state" / "projects.yml").write_text(yaml.safe_dump(registry))
    return home


def _stub_drivers(monkeypatch: pytest.MonkeyPatch, latest: str | None) -> None:
    """Stub every driver's latest_version + install + uninstall."""
    monkeypatch.setattr(
        tools_mod.NpmGlobalDriver,
        "latest_version",
        lambda self, tool, *, timeout: latest,
    )
    monkeypatch.setattr(
        tools_mod.GithubReleaseDriver,
        "latest_version",
        lambda self, tool, *, timeout: latest,
    )
    monkeypatch.setattr(
        tools_mod.AstralInstallDriver,
        "latest_version",
        lambda self, tool, *, timeout: latest,
    )

    def fake_install(self, tool, root, version):  # noqa: ANN001
        target = root / "versions" / version / "bin"
        target.mkdir(parents=True, exist_ok=True)
        binary = target / tool.binary_name
        binary.write_text("#!/bin/sh\necho dummy\n")
        return tools_mod.InstallResult(version=version, size_bytes=64)

    monkeypatch.setattr(tools_mod.NpmGlobalDriver, "install", fake_install)


def _stub_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pc, "container_name", lambda project_id: f"asdd-project-{project_id}")
    monkeypatch.setattr(pc, "is_persistent_running", lambda project_id: False)
    monkeypatch.setattr(pc, "bounce_persistent_claude", lambda project_id: False)
    monkeypatch.setattr(tools_mod, "read_baseline_version", lambda container_name, tool_name: None)


def test_cmd_upgrade_happy_path(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_drivers(monkeypatch, latest="2.1.151")
    _stub_container(monkeypatch)

    result = bootstrap.cmd_upgrade(
        asdd_home=asdd_home,
        project_id="dev",
        tool_name="claude",
        reload=False,
    )
    assert result["to"] == "2.1.151"
    assert result["noop"] is False

    manifest = tool_manifest.load(asdd_home, "dev", "claude")
    assert manifest is not None
    assert manifest.current_version == "2.1.151"
    assert len(manifest.history) == 1

    # Aggregate symlink points at the new version.
    bin_link = asdd_home / "_state" / "tools" / "dev" / "bin" / "claude"
    assert bin_link.is_symlink()
    assert "2.1.151" in str(bin_link.readlink())


def test_cmd_upgrade_noop_when_current(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_drivers(monkeypatch, latest="2.1.151")
    _stub_container(monkeypatch)

    bootstrap.cmd_upgrade(asdd_home=asdd_home, project_id="dev", tool_name="claude")
    # Second call MUST be a no-op.
    result = bootstrap.cmd_upgrade(
        asdd_home=asdd_home, project_id="dev", tool_name="claude"
    )
    assert result["noop"] is True


def test_cmd_upgrade_pin_violation(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_drivers(monkeypatch, latest="2.1.151")
    _stub_container(monkeypatch)

    bootstrap.cmd_upgrade(asdd_home=asdd_home, project_id="dev", tool_name="claude")
    bootstrap.cmd_pin(
        asdd_home=asdd_home, project_id="dev", tool_name="claude", version="2.1.151"
    )

    # New version becomes available; pin must block.
    _stub_drivers(monkeypatch, latest="2.1.152")
    with pytest.raises(bootstrap.PinViolationError):
        bootstrap.cmd_upgrade(asdd_home=asdd_home, project_id="dev", tool_name="claude")


def test_cmd_upgrade_unknown_tool_raises(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_container(monkeypatch)
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.cmd_upgrade(
            asdd_home=asdd_home, project_id="dev", tool_name="not-a-real-tool"
        )


def test_cmd_upgrade_registry_unreachable(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_drivers(monkeypatch, latest=None)
    _stub_container(monkeypatch)
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.cmd_upgrade(asdd_home=asdd_home, project_id="dev", tool_name="claude")


def test_cmd_upgrade_evicts_third_version(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After 3 successful upgrades, only the last 2 versions are retained."""
    _stub_container(monkeypatch)
    for ver in ("1.0.0", "1.0.1", "1.0.2"):
        _stub_drivers(monkeypatch, latest=ver)
        bootstrap.cmd_upgrade(
            asdd_home=asdd_home, project_id="dev", tool_name="claude"
        )

    manifest = tool_manifest.load(asdd_home, "dev", "claude")
    assert manifest is not None
    assert [h.version for h in manifest.history] == ["1.0.2", "1.0.1"]

    # And the evicted 1.0.0 directory was removed.
    evicted_dir = (
        asdd_home / "_state" / "tools" / "dev" / "claude" / "versions" / "1.0.0"
    )
    assert not evicted_dir.exists()


def test_cmd_rollback_swaps_history(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_container(monkeypatch)
    _stub_drivers(monkeypatch, latest="1.0.0")
    bootstrap.cmd_upgrade(asdd_home=asdd_home, project_id="dev", tool_name="claude")
    _stub_drivers(monkeypatch, latest="1.0.1")
    bootstrap.cmd_upgrade(asdd_home=asdd_home, project_id="dev", tool_name="claude")

    result = bootstrap.cmd_rollback(
        asdd_home=asdd_home, project_id="dev", tool_name="claude"
    )
    assert result["from"] == "1.0.1"
    assert result["to"] == "1.0.0"

    manifest = tool_manifest.load(asdd_home, "dev", "claude")
    assert manifest is not None
    assert manifest.current_version == "1.0.0"

    # Symlink follows.
    bin_link = asdd_home / "_state" / "tools" / "dev" / "bin" / "claude"
    assert "1.0.0" in str(bin_link.readlink())

    # Rollback is symmetric.
    bootstrap.cmd_rollback(
        asdd_home=asdd_home, project_id="dev", tool_name="claude"
    )
    manifest = tool_manifest.load(asdd_home, "dev", "claude")
    assert manifest.current_version == "1.0.1"


def test_cmd_rollback_no_prior(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_container(monkeypatch)
    _stub_drivers(monkeypatch, latest="1.0.0")
    bootstrap.cmd_upgrade(asdd_home=asdd_home, project_id="dev", tool_name="claude")
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.cmd_rollback(
            asdd_home=asdd_home, project_id="dev", tool_name="claude"
        )


def test_cmd_pin_requires_match(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_container(monkeypatch)
    _stub_drivers(monkeypatch, latest="1.0.0")
    bootstrap.cmd_upgrade(asdd_home=asdd_home, project_id="dev", tool_name="claude")
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.cmd_pin(
            asdd_home=asdd_home,
            project_id="dev",
            tool_name="claude",
            version="9.9.9",
        )


def test_cmd_unpin_idempotent(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_container(monkeypatch)
    _stub_drivers(monkeypatch, latest="1.0.0")
    bootstrap.cmd_upgrade(asdd_home=asdd_home, project_id="dev", tool_name="claude")
    result = bootstrap.cmd_unpin(
        asdd_home=asdd_home, project_id="dev", tool_name="claude"
    )
    assert result["noop"] is True


def test_cmd_reset_tools_single(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_container(monkeypatch)
    _stub_drivers(monkeypatch, latest="1.0.0")
    bootstrap.cmd_upgrade(asdd_home=asdd_home, project_id="dev", tool_name="claude")

    project_dir = asdd_home / "_state" / "tools" / "dev"
    assert (project_dir / "claude").exists()
    assert (project_dir / "bin" / "claude").is_symlink()

    result = bootstrap.cmd_reset_tools(
        asdd_home=asdd_home, project_id="dev", tool_name="claude"
    )
    assert "claude" in result["cleared"]
    assert not (project_dir / "claude").exists()
    assert not (project_dir / "bin" / "claude").exists()


def test_cmd_reset_tools_idempotent(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_container(monkeypatch)
    result = bootstrap.cmd_reset_tools(
        asdd_home=asdd_home, project_id="dev", tool_name="claude"
    )
    assert result["cleared"] == []


def test_cmd_versions_marks_update_available(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_container(monkeypatch)
    _stub_drivers(monkeypatch, latest="1.0.0")
    bootstrap.cmd_upgrade(asdd_home=asdd_home, project_id="dev", tool_name="claude")
    _stub_drivers(monkeypatch, latest="1.0.1")
    # Clear the version cache so the new latest is fetched.
    cache_path = asdd_home / "_state" / "tools" / ".version-cache.json"
    if cache_path.exists():
        cache_path.unlink()

    result = bootstrap.cmd_versions(asdd_home=asdd_home, project_id="dev")
    claude_row = next(r for r in result["tools"] if r["tool"] == "claude")
    assert claude_row["installed"] == "1.0.0"
    assert claude_row["latest"] == "1.0.1"
    assert claude_row["status"] == "update available"


def test_stale_tools_for_banner_skips_pinned(
    asdd_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_container(monkeypatch)
    _stub_drivers(monkeypatch, latest="1.0.0")
    bootstrap.cmd_upgrade(asdd_home=asdd_home, project_id="dev", tool_name="claude")
    bootstrap.cmd_pin(
        asdd_home=asdd_home, project_id="dev", tool_name="claude", version="1.0.0"
    )
    _stub_drivers(monkeypatch, latest="1.0.1")
    cache_path = asdd_home / "_state" / "tools" / ".version-cache.json"
    if cache_path.exists():
        cache_path.unlink()

    stale = bootstrap.stale_tools_for_banner(asdd_home, "dev")
    assert all(line.tool != "claude" for line in stale)
