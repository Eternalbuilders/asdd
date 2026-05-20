"""Unit tests for asdd/audit.py (T027).

Asserts: schema validation, atomic append, never-edits-rows invariant.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from asdd._schemas import AuditValidationError
from asdd.audit import append


def _read_rows(asdd_home: Path) -> list[dict]:
    audit_log = asdd_home / "_state" / "audit.log"
    if not audit_log.exists():
        return []
    return [json.loads(ln) for ln in audit_log.read_text().splitlines() if ln.strip()]


def test_append_writes_one_row(tmp_path: Path) -> None:
    append(
        "cross_project_attempt",
        asdd_home=tmp_path,
        project_id="vaultcontrol",
        path="/asdd_home/projects/acme-unity/_state/secrets.enc.yml",
    )
    rows = _read_rows(tmp_path)
    assert len(rows) == 1
    r = rows[0]
    assert r["kind"] == "cross_project_attempt"
    assert r["project_id"] == "vaultcontrol"
    assert "ts_utc" in r and r["ts_utc"].endswith("Z")


def test_append_two_rows_appends_not_overwrites(tmp_path: Path) -> None:
    append("kernel_bug", asdd_home=tmp_path, detail={"reason": "first"})
    append("kernel_bug", asdd_home=tmp_path, detail={"reason": "second"})
    rows = _read_rows(tmp_path)
    assert len(rows) == 2
    assert rows[0]["detail"]["reason"] == "first"
    assert rows[1]["detail"]["reason"] == "second"


def test_append_rejects_unknown_kind(tmp_path: Path) -> None:
    with pytest.raises(AuditValidationError):
        append("not_a_real_kind", asdd_home=tmp_path)


def test_append_rejects_bad_project_id_regex(tmp_path: Path) -> None:
    with pytest.raises(AuditValidationError):
        append("cross_project_attempt", asdd_home=tmp_path, project_id="BAD CAPS")


def test_append_creates_state_dir(tmp_path: Path) -> None:
    # No _state/ dir pre-existing
    assert not (tmp_path / "_state").exists()
    append("kernel_bug", asdd_home=tmp_path)
    assert (tmp_path / "_state" / "audit.log").exists()
