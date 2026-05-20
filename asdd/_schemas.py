"""JSON Schema validator loader for ASDD platform contracts.

Loads ``projects.yml.schema.json`` and ``audit-log.schema.json`` from
``asdd/contracts/`` at import time and exposes validator functions.
Raises ``RegistryLoadError`` / ``AuditValidationError`` on invalidity so
callers can distinguish schema failure from I/O failure.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema


class RegistryLoadError(ValueError):
    """The registry file is missing, malformed, or schema-invalid."""


class AuditValidationError(ValueError):
    """The audit row does not match the audit-log schema."""


def _contracts_root() -> Path:
    # Schemas ship inside the package at asdd/contracts/. No fallback path —
    # if this directory is missing, the install is broken.
    path = Path(__file__).resolve().parent / "contracts"
    if not path.is_dir():
        raise FileNotFoundError(
            f"asdd contracts directory not found at {path}; install is broken"
        )
    return path


def _load_schema(name: str) -> dict[str, Any]:
    path = _contracts_root() / name
    with path.open() as f:
        return json.load(f)


_REGISTRY_SCHEMA = _load_schema("projects.yml.schema.json")
_AUDIT_SCHEMA = _load_schema("audit-log.schema.json")

_REGISTRY_VALIDATOR = jsonschema.Draft202012Validator(_REGISTRY_SCHEMA)
_AUDIT_VALIDATOR = jsonschema.Draft202012Validator(_AUDIT_SCHEMA)


def validate_registry(obj: Any) -> None:
    """Raise RegistryLoadError if ``obj`` does not match the registry schema."""
    errors = sorted(_REGISTRY_VALIDATOR.iter_errors(obj), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        path = ".".join(str(p) for p in first.absolute_path) or "<root>"
        raise RegistryLoadError(f"projects.yml schema-invalid at {path}: {first.message}")


def validate_audit_row(obj: Any) -> None:
    """Raise AuditValidationError if ``obj`` does not match the audit-log schema."""
    errors = sorted(_AUDIT_VALIDATOR.iter_errors(obj), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        path = ".".join(str(p) for p in first.absolute_path) or "<root>"
        raise AuditValidationError(f"audit row schema-invalid at {path}: {first.message}")


__all__ = [
    "RegistryLoadError",
    "AuditValidationError",
    "validate_registry",
    "validate_audit_row",
]
