"""Mtime-based hot reload of the project registry (T011).

The kernel's tick loop calls ``RegistryWatcher.reload_if_changed()`` once per
tick. On parse / schema failure the previously-loaded registry is kept and a
``registry_load_error`` row is appended to the platform audit log; the
kernel keeps running.
"""

from __future__ import annotations

import logging
from pathlib import Path

from asdd import audit
from asdd._schemas import RegistryLoadError
from asdd.registry import Registry, load

log = logging.getLogger(__name__)


class RegistryWatcher:
    """Holds the current Registry and reloads when the file's mtime changes."""

    def __init__(self, registry_path: Path, *, asdd_home: Path) -> None:
        self._path = registry_path
        self._asdd_home = asdd_home
        self._last_mtime_ns: int | None = None
        self._current: Registry | None = None
        # Eagerly load so callers can rely on .current() before the first tick.
        self._reload(emit_audit_on_failure=False)

    def current(self) -> Registry:
        """Return the most-recently-good registry.

        Raises:
            RegistryLoadError: if no registry has ever loaded successfully.
        """
        if self._current is None:
            raise RegistryLoadError(f"registry has never loaded successfully from {self._path}")
        return self._current

    def reload_if_changed(self) -> Registry:
        """Re-read the registry only if its mtime has changed.

        On parse / schema failure: keep the previous registry, emit an audit
        row, and return the previous registry (so the caller never sees a
        partially-loaded view).
        """
        try:
            mtime = self._path.stat().st_mtime_ns
        except FileNotFoundError:
            if self._current is None:
                raise RegistryLoadError(f"projects.yml not found at {self._path}") from None
            # File disappeared. Keep the cached copy, emit audit.
            audit.append(
                "registry_load_error",
                asdd_home=self._asdd_home,
                detail={"path": str(self._path), "reason": "file_disappeared"},
            )
            return self._current

        if self._last_mtime_ns is not None and mtime == self._last_mtime_ns:
            assert self._current is not None
            return self._current

        self._reload(emit_audit_on_failure=True)
        assert self._current is not None
        return self._current

    def _reload(self, *, emit_audit_on_failure: bool) -> None:
        try:
            new_registry = load(self._path)
        except RegistryLoadError as e:
            if emit_audit_on_failure:
                audit.append(
                    "registry_load_error",
                    asdd_home=self._asdd_home,
                    detail={"path": str(self._path), "reason": str(e)},
                )
            log.warning("registry reload failed, keeping previous: %s", e)
            if self._current is None:
                # No previously-good registry — propagate so the caller can decide.
                raise
            return
        self._current = new_registry
        self._last_mtime_ns = self._path.stat().st_mtime_ns


__all__ = ["RegistryWatcher"]
