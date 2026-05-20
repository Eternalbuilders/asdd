"""Migration 001 — add project_id column to ledger_row (T017).

Idempotent: catches the SQLite "duplicate column name" error and continues.
After running, asserts that no row has NULL/empty ``project_id``.

Usage:
    python -m asdd.migrations.m001_add_project_id_to_ledger /path/to/tokens.sqlite
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def _migration_sql() -> tuple[str, str]:
    """Return the two DDL statements; we execute them individually so the
    first being a no-op (already added) doesn't block the second."""
    return (
        "ALTER TABLE ledger_row ADD COLUMN project_id TEXT NOT NULL DEFAULT 'vaultcontrol'",
        "CREATE INDEX IF NOT EXISTS idx_ledger_project_window "
        "ON ledger_row (project_id, ts_utc)",
    )


def run(db_path: Path) -> dict:
    """Apply the migration; return a small status report."""
    report: dict = {"db": str(db_path), "alter_table": "skipped", "create_index": "ok"}

    conn = sqlite3.connect(db_path)
    try:
        alter_sql, index_sql = _migration_sql()

        try:
            conn.execute(alter_sql)
            report["alter_table"] = "applied"
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                report["alter_table"] = "skipped"
            else:
                raise

        conn.execute(index_sql)

        # Verification — zero rows with NULL or empty project_id
        cur = conn.execute(
            "SELECT COUNT(*) FROM ledger_row " "WHERE project_id IS NULL OR project_id = ''"
        )
        (bad,) = cur.fetchone()
        report["null_or_empty_project_id_count"] = bad
        if bad != 0:
            raise RuntimeError(
                f"migration verification failed: {bad} ledger rows have NULL/empty project_id"
            )

        conn.commit()
    finally:
        conn.close()
    return report


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print(
            "usage: python -m asdd.migrations.m001_add_project_id_to_ledger <tokens.sqlite>",
            file=sys.stderr,
        )
        return 2
    db = Path(args[0])
    report = run(db)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
