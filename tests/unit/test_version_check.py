"""Unit tests for asdd/version_check.py — spec 002 Phase 2."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from asdd import tools as tools_mod
from asdd import version_check as vc


def test_cache_hit_returns_value(tmp_path: Path) -> None:
    cache = vc.VersionCache.load(tmp_path)
    cache.set("claude", "2.1.151")
    cache.save()

    loaded = vc.VersionCache.load(tmp_path)
    assert loaded.get("claude") == "2.1.151"


def test_cache_miss_returns_none(tmp_path: Path) -> None:
    cache = vc.VersionCache.load(tmp_path)
    assert cache.get("never-set") is None


def test_cache_stale_entry_is_ignored(tmp_path: Path) -> None:
    cache = vc.VersionCache.load(tmp_path)
    cache.entries["claude"] = vc.CacheEntry(
        tool_name="claude",
        latest_version="0.0.1",
        checked_at=int(time.time()) - vc.CACHE_TTL_SEC - 10,
    )
    assert cache.get("claude") is None


def test_check_latest_uses_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = vc.VersionCache.load(tmp_path)
    cache.set("claude", "1.0.0")
    cache.save()

    # If the driver were called, it would be a real network call. Stub it
    # so the test would fail loudly if cache wasn't respected.
    def boom(*args, **kwargs):  # noqa: ANN001
        pytest.fail("driver should not be called on cache hit")

    monkeypatch.setattr(tools_mod.NpmGlobalDriver, "latest_version", boom)
    result = vc.check_latest(tmp_path, tools_mod.TOOLS["claude"])
    assert result == "1.0.0"


def test_check_latest_falls_through_on_cache_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def stub(self, tool, *, timeout):  # noqa: ANN001
        assert tool.name == "claude"
        assert timeout == vc.PROBE_TIMEOUT_SEC
        return "2.1.151"

    monkeypatch.setattr(tools_mod.NpmGlobalDriver, "latest_version", stub)
    result = vc.check_latest(tmp_path, tools_mod.TOOLS["claude"])
    assert result == "2.1.151"
    # And the cache now has the value.
    assert vc.VersionCache.load(tmp_path).get("claude") == "2.1.151"


def test_check_latest_returns_none_on_driver_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        tools_mod.NpmGlobalDriver, "latest_version", lambda self, tool, *, timeout: None
    )
    result = vc.check_latest(tmp_path, tools_mod.TOOLS["claude"])
    assert result is None
    # Cache MUST NOT record a failure (or the next probe would be incorrectly suppressed).
    assert vc.VersionCache.load(tmp_path).get("claude") is None


def test_check_all_runs_in_parallel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    versions = {"claude": "2.1.151", "gh": "2.95.0", "uv": "0.4.12"}

    def npm_latest(self, tool, *, timeout):  # noqa: ANN001
        return versions[tool.name]

    def gh_latest(self, tool, *, timeout):  # noqa: ANN001
        return versions[tool.name]

    monkeypatch.setattr(tools_mod.NpmGlobalDriver, "latest_version", npm_latest)
    monkeypatch.setattr(tools_mod.GithubReleaseDriver, "latest_version", gh_latest)
    monkeypatch.setattr(tools_mod.AstralInstallDriver, "latest_version", gh_latest)

    result = vc.check_all(tmp_path)
    assert result == versions


def test_check_all_respects_partial_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = vc.VersionCache.load(tmp_path)
    cache.set("claude", "PRE-CACHED")
    cache.save()

    def gh_latest(self, tool, *, timeout):  # noqa: ANN001
        return "fresh"

    monkeypatch.setattr(tools_mod.GithubReleaseDriver, "latest_version", gh_latest)
    monkeypatch.setattr(tools_mod.AstralInstallDriver, "latest_version", gh_latest)
    # claude must NOT be called.
    monkeypatch.setattr(
        tools_mod.NpmGlobalDriver,
        "latest_version",
        lambda self, tool, *, timeout: pytest.fail("cache hit must skip probe"),
    )

    result = vc.check_all(tmp_path)
    assert result["claude"] == "PRE-CACHED"
    assert result["gh"] == "fresh"
    assert result["uv"] == "fresh"
