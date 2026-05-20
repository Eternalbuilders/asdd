"""Append-only platform audit log (T013).

Writes one schema-validated JSON line per security-relevant event to
``${ASDD_HOME}/_state/audit.log``. Never edits or deletes rows.

Open with ``O_APPEND`` so concurrent writers from different processes do
not interleave bytes (POSIX guarantees atomicity for writes ≤ PIPE_BUF;
JSON rows are small).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from asdd._schemas import AuditValidationError, validate_audit_row

# These literal values match contracts/audit-log.schema.json#/properties/kind/enum
AuditKind = str  # narrowing to a Literal would cost circular complexity; runtime-validated


def _iso_utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _audit_path(asdd_home: Path) -> Path:
    return asdd_home / "_state" / "audit.log"


def append(
    kind: AuditKind,
    *,
    asdd_home: Path,
    project_id: str | None = None,
    path: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append one schema-validated audit row.

    Args:
        kind: must match the audit-log schema's kind enum
        asdd_home: platform root (``${ASDD_HOME}``)
        project_id: offending project, if applicable
        path: offending path, if applicable
        detail: free-form structured payload

    Raises:
        AuditValidationError: if the assembled row does not match the schema
    """
    row: dict[str, Any] = {"ts_utc": _iso_utc_now(), "kind": kind}
    if project_id is not None:
        row["project_id"] = project_id
    if path is not None:
        row["path"] = path
    if detail is not None:
        row["detail"] = detail

    validate_audit_row(row)

    audit_file = _audit_path(asdd_home)
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, separators=(",", ":")) + "\n"
    # O_APPEND ensures each write is atomically positioned at EOF; short writes
    # of small JSON rows are atomic on POSIX.
    fd = os.open(audit_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


__all__ = ["AuditValidationError", "append"]
