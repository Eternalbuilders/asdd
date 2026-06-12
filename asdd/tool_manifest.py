"""Per-tool manifest read/write + lock helper (spec 002).

The manifest is a single JSON file at
``$ASDD_HOME/_state/tools/<project_id>/<tool>/manifest.json`` recording
``current_version``, ``history`` (capped at 2), and optional ``pin``.

Atomic writes via ``tmp`` + ``rename``. Schema version checking refuses
unknown shapes. ``acquire_lock`` is a context manager around
``fcntl.flock(LOCK_EX | LOCK_NB)`` for per-(project, tool) serialization.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1
HISTORY_CAP = 2
MANIFEST_FILENAME = "manifest.json"
LOCK_FILENAME = ".lock"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ManifestError(Exception):
    """Base class for manifest errors."""


class LockBusyError(ManifestError):
    """The per-(project, tool) lock could not be acquired."""


class SchemaVersionError(ManifestError):
    """Manifest's schema_version is not ``SCHEMA_VERSION``."""


class ManifestValidationError(ManifestError):
    """The manifest violates an invariant (e.g., history > 2)."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class VersionRecord:
    version: str
    installed_at: int
    install_method: str
    size_bytes: int


@dataclass
class Pin:
    version: str
    set_at: int


@dataclass
class Manifest:
    tool_name: str
    current_version: str
    history: list[VersionRecord] = field(default_factory=list)
    pin: Pin | None = None
    last_checked_at: int | None = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        out = {
            "schema_version": self.schema_version,
            "tool_name": self.tool_name,
            "current_version": self.current_version,
            "history": [asdict(h) for h in self.history],
            "pin": asdict(self.pin) if self.pin else None,
            "last_checked_at": self.last_checked_at,
        }
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Manifest":
        if "schema_version" not in data:
            raise SchemaVersionError("manifest is missing schema_version")
        if data["schema_version"] != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"unsupported manifest schema_version {data['schema_version']}; "
                f"this asdd understands {SCHEMA_VERSION}"
            )
        try:
            history = [VersionRecord(**h) for h in data.get("history", [])]
            pin_data = data.get("pin")
            pin = Pin(**pin_data) if pin_data else None
            return cls(
                tool_name=data["tool_name"],
                current_version=data["current_version"],
                history=history,
                pin=pin,
                last_checked_at=data.get("last_checked_at"),
                schema_version=data["schema_version"],
            )
        except (KeyError, TypeError) as e:
            raise ManifestValidationError(f"manifest malformed: {e}") from e

    def validate(self) -> None:
        """Raise ``ManifestValidationError`` if invariants are broken."""
        if not self.tool_name:
            raise ManifestValidationError("tool_name is required")
        if not self.current_version:
            raise ManifestValidationError("current_version is required")
        if not self.history:
            raise ManifestValidationError("history MUST have at least one entry")
        if len(self.history) > HISTORY_CAP:
            raise ManifestValidationError(
                f"history MUST have at most {HISTORY_CAP} entries; got {len(self.history)}"
            )
        if self.history[0].version != self.current_version:
            raise ManifestValidationError(
                f"history[0].version ({self.history[0].version}) must equal "
                f"current_version ({self.current_version})"
            )
        if self.pin and self.pin.version != self.current_version:
            raise ManifestValidationError(
                f"pin.version ({self.pin.version}) must equal "
                f"current_version ({self.current_version})"
            )


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def project_tools_dir(asdd_home: Path, project_id: str) -> Path:
    """Return the per-project overlay root on the host.

    Layout: ``$ASDD_HOME/_state/tools/<project_id>/``.
    """
    return asdd_home / "_state" / "tools" / project_id


def tool_dir(asdd_home: Path, project_id: str, tool_name: str) -> Path:
    """Return ``<project_overlay>/<tool_name>/`` (the per-tool subdir)."""
    return project_tools_dir(asdd_home, project_id) / tool_name


def manifest_path(asdd_home: Path, project_id: str, tool_name: str) -> Path:
    return tool_dir(asdd_home, project_id, tool_name) / MANIFEST_FILENAME


def lock_path(asdd_home: Path, project_id: str, tool_name: str) -> Path:
    return tool_dir(asdd_home, project_id, tool_name) / LOCK_FILENAME


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------


def load(asdd_home: Path, project_id: str, tool_name: str) -> Manifest | None:
    """Read the on-disk manifest. Returns None if it doesn't exist."""
    path = manifest_path(asdd_home, project_id, tool_name)
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    m = Manifest.from_dict(data)
    m.validate()
    return m


def save(asdd_home: Path, project_id: str, manifest: Manifest) -> None:
    """Atomically write the manifest to disk.

    Creates the per-tool dir and any parents (``0700``) if missing.
    """
    manifest.validate()
    target_dir = tool_dir(asdd_home, project_id, manifest.tool_name)
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    target_path = target_dir / MANIFEST_FILENAME
    tmp_path = target_dir / f"{MANIFEST_FILENAME}.tmp"
    payload = json.dumps(manifest.to_dict(), indent=2, sort_keys=True)
    tmp_path.write_text(payload, encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, target_path)


# ---------------------------------------------------------------------------
# History truncation + eviction
# ---------------------------------------------------------------------------


def push_history(manifest: Manifest, new_record: VersionRecord) -> str | None:
    """Prepend ``new_record`` to history; return the evicted version (or None).

    Caller is responsible for actually removing the evicted version's files
    via the driver's ``uninstall``. We just return the name.
    """
    if any(h.version == new_record.version for h in manifest.history):
        # Replace the existing record instead of duplicating.
        manifest.history = [h for h in manifest.history if h.version != new_record.version]
    manifest.history.insert(0, new_record)
    evicted = None
    while len(manifest.history) > HISTORY_CAP:
        evicted = manifest.history.pop().version
    manifest.current_version = manifest.history[0].version
    return evicted


# ---------------------------------------------------------------------------
# Lock context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def acquire_lock(asdd_home: Path, project_id: str, tool_name: str) -> Iterator[None]:
    """Hold an exclusive lock for the duration of the ``with`` block.

    Non-blocking: if another process holds the lock, raise ``LockBusyError``
    immediately so the operator sees a clear "already in progress" message.
    """
    target_dir = tool_dir(asdd_home, project_id, tool_name)
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = target_dir / LOCK_FILENAME
    path.touch(mode=0o600, exist_ok=True)
    fd = os.open(path, os.O_RDWR)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise LockBusyError(
                f"upgrade for {tool_name} in {project_id} already in progress"
            ) from e
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Upgrade log (append-only)
# ---------------------------------------------------------------------------


def append_upgrade_log(
    asdd_home: Path,
    project_id: str,
    tool_name: str,
    *,
    action: str,
    from_version: str | None,
    to_version: str | None,
    exit_code: int,
    duration_ms: int,
) -> None:
    """Append one line to ``<tool>/upgrade.log``."""
    target_dir = tool_dir(asdd_home, project_id, tool_name)
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path = target_dir / "upgrade.log"
    line = (
        f"{int(time.time())}\t{action}\t"
        f"{from_version or '-'}\t{to_version or '-'}\t"
        f"exit={exit_code}\tduration_ms={duration_ms}\n"
    )
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)
