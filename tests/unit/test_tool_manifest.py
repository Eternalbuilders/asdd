"""Unit tests for asdd/tool_manifest.py — spec 002 Phase 2."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from asdd import tool_manifest as tm


def _record(version: str, when: int = 100) -> tm.VersionRecord:
    return tm.VersionRecord(
        version=version,
        installed_at=when,
        install_method="npm-global",
        size_bytes=1234,
    )


def test_save_then_load_roundtrips(tmp_path: Path) -> None:
    m = tm.Manifest(
        tool_name="claude",
        current_version="2.1.150",
        history=[_record("2.1.150")],
        pin=None,
        last_checked_at=999,
    )
    tm.save(tmp_path, "dev", m)
    loaded = tm.load(tmp_path, "dev", "claude")
    assert loaded is not None
    assert loaded.tool_name == "claude"
    assert loaded.current_version == "2.1.150"
    assert len(loaded.history) == 1
    assert loaded.history[0].version == "2.1.150"
    assert loaded.pin is None


def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert tm.load(tmp_path, "dev", "claude") is None


def test_validate_rejects_history_over_cap(tmp_path: Path) -> None:
    m = tm.Manifest(
        tool_name="claude",
        current_version="3",
        history=[_record("3"), _record("2"), _record("1")],
    )
    with pytest.raises(tm.ManifestValidationError):
        tm.save(tmp_path, "dev", m)


def test_validate_rejects_current_mismatch(tmp_path: Path) -> None:
    m = tm.Manifest(
        tool_name="claude",
        current_version="X",
        history=[_record("Y")],
    )
    with pytest.raises(tm.ManifestValidationError):
        tm.save(tmp_path, "dev", m)


def test_validate_rejects_pin_mismatch(tmp_path: Path) -> None:
    m = tm.Manifest(
        tool_name="claude",
        current_version="A",
        history=[_record("A")],
        pin=tm.Pin(version="B", set_at=100),
    )
    with pytest.raises(tm.ManifestValidationError):
        tm.save(tmp_path, "dev", m)


def test_load_rejects_unknown_schema(tmp_path: Path) -> None:
    # Write a bogus schema_version directly.
    tool_dir = tm.tool_dir(tmp_path, "dev", "claude")
    tool_dir.mkdir(parents=True, exist_ok=True)
    (tool_dir / tm.MANIFEST_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 999,
                "tool_name": "claude",
                "current_version": "1",
                "history": [],
                "pin": None,
            }
        )
    )
    with pytest.raises(tm.SchemaVersionError):
        tm.load(tmp_path, "dev", "claude")


def test_push_history_caps_at_two_and_evicts_oldest() -> None:
    m = tm.Manifest(
        tool_name="claude",
        current_version="1",
        history=[_record("1")],
    )
    evicted_a = tm.push_history(m, _record("2"))
    assert evicted_a is None
    assert m.current_version == "2"
    assert [h.version for h in m.history] == ["2", "1"]

    evicted_b = tm.push_history(m, _record("3"))
    assert evicted_b == "1"
    assert [h.version for h in m.history] == ["3", "2"]


def test_push_history_dedupes_existing_version() -> None:
    m = tm.Manifest(
        tool_name="claude",
        current_version="1",
        history=[_record("1"), _record("0")],
    )
    # Re-pushing version "1" must not push current down to history[1].
    evicted = tm.push_history(m, _record("1", when=200))
    assert evicted is None
    assert m.history[0].version == "1"
    assert m.history[0].installed_at == 200


def test_acquire_lock_exclusive(tmp_path: Path) -> None:
    with tm.acquire_lock(tmp_path, "dev", "claude"):
        # Second non-blocking acquire from same process MUST raise.
        with pytest.raises(tm.LockBusyError):
            with tm.acquire_lock(tmp_path, "dev", "claude"):
                pytest.fail("second acquire should have failed")


def test_acquire_lock_releases_on_exit(tmp_path: Path) -> None:
    with tm.acquire_lock(tmp_path, "dev", "claude"):
        pass
    # New acquire should succeed.
    with tm.acquire_lock(tmp_path, "dev", "claude"):
        pass


def test_acquire_lock_different_tools_dont_block(tmp_path: Path) -> None:
    with tm.acquire_lock(tmp_path, "dev", "claude"):
        with tm.acquire_lock(tmp_path, "dev", "gh"):
            pass


def test_append_upgrade_log_appends_lines(tmp_path: Path) -> None:
    tm.append_upgrade_log(
        tmp_path,
        "dev",
        "claude",
        action="upgrade",
        from_version="2.1.150",
        to_version="2.1.151",
        exit_code=0,
        duration_ms=1234,
    )
    tm.append_upgrade_log(
        tmp_path,
        "dev",
        "claude",
        action="rollback",
        from_version="2.1.151",
        to_version="2.1.150",
        exit_code=0,
        duration_ms=10,
    )
    log = (tm.tool_dir(tmp_path, "dev", "claude") / "upgrade.log").read_text()
    assert "upgrade" in log
    assert "rollback" in log
    assert "2.1.151" in log
