"""Upstream version checks + a 5-minute cross-project cache (spec 002).

A driver's ``latest_version`` does the network round-trip; this module wraps
those calls with a host-wide JSON cache (``.version-cache.json``) so back-to-
back session-start banners and ``asdd versions`` invocations don't repeat the
work.

Concurrency: ``check_all`` runs probes in parallel via a ``ThreadPoolExecutor``
so a 3-tool, all-cold check completes in roughly the slowest single probe (≤ 2 s).
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import tools as tools_mod

CACHE_FILENAME = ".version-cache.json"
CACHE_TTL_SEC = 300  # 5 minutes; see plan R10.
PROBE_TIMEOUT_SEC = tools_mod.DEFAULT_PROBE_TIMEOUT_SEC
MAX_PARALLEL_PROBES = 8


@dataclass
class CacheEntry:
    tool_name: str
    latest_version: str | None
    checked_at: int


@dataclass
class VersionCache:
    """Single host-wide upstream-version cache.

    Path: ``$ASDD_HOME/_state/tools/.version-cache.json``. Entries older than
    ``CACHE_TTL_SEC`` are ignored on read; a successful probe overwrites the
    entry for that tool. A failed probe leaves the entry alone.
    """

    asdd_home: Path
    entries: dict[str, CacheEntry] = field(default_factory=dict)

    @classmethod
    def load(cls, asdd_home: Path) -> "VersionCache":
        path = cls._path(asdd_home)
        if not path.exists():
            return cls(asdd_home=asdd_home)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = {
                e["tool_name"]: CacheEntry(
                    tool_name=e["tool_name"],
                    latest_version=e.get("latest_version"),
                    checked_at=int(e["checked_at"]),
                )
                for e in data.get("entries", [])
            }
            return cls(asdd_home=asdd_home, entries=entries)
        except (OSError, ValueError, KeyError):
            return cls(asdd_home=asdd_home)

    def save(self) -> None:
        path = self._path(self.asdd_home)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = {
            "entries": [
                {
                    "tool_name": e.tool_name,
                    "latest_version": e.latest_version,
                    "checked_at": e.checked_at,
                }
                for e in sorted(self.entries.values(), key=lambda x: x.tool_name)
            ]
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

    def get(self, tool_name: str) -> str | None:
        """Return cached latest version if fresh; else None."""
        entry = self.entries.get(tool_name)
        if entry is None:
            return None
        if time.time() - entry.checked_at > CACHE_TTL_SEC:
            return None
        return entry.latest_version

    def set(self, tool_name: str, latest_version: str | None) -> None:
        self.entries[tool_name] = CacheEntry(
            tool_name=tool_name,
            latest_version=latest_version,
            checked_at=int(time.time()),
        )

    @staticmethod
    def _path(asdd_home: Path) -> Path:
        return asdd_home / "_state" / "tools" / CACHE_FILENAME


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_latest(
    asdd_home: Path,
    tool: tools_mod.ManagedTool,
    *,
    timeout: float = PROBE_TIMEOUT_SEC,
    use_cache: bool = True,
) -> str | None:
    """Return the latest upstream version of ``tool``, or None on failure.

    Updates the host-wide cache on success. On a cache hit, no network call
    is made.
    """
    cache = VersionCache.load(asdd_home)
    if use_cache:
        cached = cache.get(tool.name)
        if cached is not None:
            return cached
    driver = tools_mod.driver_for(tool)
    latest = driver.latest_version(tool, timeout=timeout)
    if latest is not None:
        cache.set(tool.name, latest)
        cache.save()
    return latest


def check_all(
    asdd_home: Path,
    *,
    timeout: float = PROBE_TIMEOUT_SEC,
    use_cache: bool = True,
    tool_names: Iterable[str] | None = None,
) -> dict[str, str | None]:
    """Return a ``{tool_name: latest_version_or_None}`` map for every tool.

    Runs probes in parallel; respects per-probe timeouts. Bounded total
    wall-clock at roughly ``timeout`` seconds (the slowest single probe).
    """
    names = list(tool_names) if tool_names else list(tools_mod.TOOLS.keys())
    cache = VersionCache.load(asdd_home)

    results: dict[str, str | None] = {}
    to_fetch: list[tools_mod.ManagedTool] = []
    for name in names:
        tool = tools_mod.get_tool(name)
        if use_cache:
            cached = cache.get(name)
            if cached is not None:
                results[name] = cached
                continue
        to_fetch.append(tool)

    if not to_fetch:
        return results

    def _probe(tool: tools_mod.ManagedTool) -> tuple[str, str | None]:
        driver = tools_mod.driver_for(tool)
        try:
            return tool.name, driver.latest_version(tool, timeout=timeout)
        except Exception:
            return tool.name, None

    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_PROBES, len(to_fetch))) as pool:
        futures = [pool.submit(_probe, t) for t in to_fetch]
        for fut in as_completed(futures):
            name, latest = fut.result()
            results[name] = latest
            if latest is not None:
                cache.set(name, latest)

    cache.save()
    return results
