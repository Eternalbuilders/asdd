"""Unit test for the ledger migration runner (T017)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from asdd.migrations.m001_add_project_id_to_ledger import run


def _create_legacy_ledger(db_path: Path) -> None:
    """Create a ledger_row table in the shape that existed before 007."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""CREATE TABLE ledger_row (
                job_id TEXT NOT NULL,
                agent TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                ts_utc TEXT NOT NULL
            )""")
        conn.execute(
            "INSERT INTO ledger_row (job_id, agent, model, input_tokens, output_tokens, ts_utc) "
            "VALUES ('j1', 'a1', 'sonnet', 100, 50, '2026-05-13T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO ledger_row (job_id, agent, model, input_tokens, output_tokens, ts_utc) "
            "VALUES ('j2', 'a2', 'opus', 200, 100, '2026-05-13T01:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()


def test_migration_adds_column_and_backfills(tmp_path: Path) -> None:
    db = tmp_path / "tokens.sqlite"
    _create_legacy_ledger(db)

    report = run(db)
    assert report["alter_table"] == "applied"
    assert report["null_or_empty_project_id_count"] == 0

    conn = sqlite3.connect(db)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(ledger_row)")}
        assert "project_id" in cols
        rows = list(conn.execute("SELECT project_id FROM ledger_row"))
        assert rows == [("vaultcontrol",), ("vaultcontrol",)]

        # Index was created
        idxs = {row[1] for row in conn.execute("PRAGMA index_list(ledger_row)")}
        assert "idx_ledger_project_window" in idxs
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "tokens.sqlite"
    _create_legacy_ledger(db)
    run(db)
    # Second run should be a no-op (skipped, not error)
    report = run(db)
    assert report["alter_table"] == "skipped"
    assert report["null_or_empty_project_id_count"] == 0
