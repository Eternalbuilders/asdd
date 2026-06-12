"""Tool registry + per-method install drivers (spec 002).

The registry declares every tool the system manages. Each tool names an install
method; each method has a driver implementing the ``ToolDriver`` Protocol that
handles install, uninstall, and upstream-version probing.

Drivers are pure file-system + subprocess workers. The orchestrator
(``asdd.bootstrap.cmd_upgrade``) owns lock acquisition, manifest writes,
symlink retargeting, and history truncation — drivers MUST NOT touch any of
those.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

ASDD_OVERLAY_MOUNT = "/home/asdd/.asdd-tools"
"""Container-side mount point for the per-project tool overlay."""

ASDD_BASELINE_DIR = "/opt/asdd-baseline"
"""Container-side baseline tools (installed at image build time)."""

DEFAULT_PROBE_TIMEOUT_SEC = 2.0
"""Default per-tool upstream version-check timeout, in seconds."""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ToolError(Exception):
    """Base class for spec-002 errors."""


class UnknownToolError(ToolError):
    """The named tool is not in the registry."""


class DriverError(ToolError):
    """A driver's install / latest_version / installed_version failed."""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

DriverMethod = Literal["npm-global", "github-release", "astral-install"]


@dataclass(frozen=True)
class ManagedTool:
    """A tool the system knows how to upgrade.

    Adding a tool = adding one ``ManagedTool`` entry to ``TOOLS``. If the
    install method is new, add a driver class as well.
    """

    name: str
    driver_method: DriverMethod
    source_id: str
    binary_name: str


TOOLS: dict[str, ManagedTool] = {
    "claude": ManagedTool(
        name="claude",
        driver_method="npm-global",
        source_id="@anthropic-ai/claude-code",
        binary_name="claude",
    ),
    "gh": ManagedTool(
        name="gh",
        driver_method="github-release",
        source_id="cli/cli",
        binary_name="gh",
    ),
    "uv": ManagedTool(
        name="uv",
        driver_method="astral-install",
        source_id="astral-sh/uv",
        binary_name="uv",
    ),
}


def get_tool(name: str) -> ManagedTool:
    """Look up a tool by name; raise ``UnknownToolError`` if absent."""
    try:
        return TOOLS[name]
    except KeyError as e:  # pragma: no cover - error path
        raise UnknownToolError(name) from e


# ---------------------------------------------------------------------------
# Driver protocol + InstallResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstallResult:
    """Returned by ``ToolDriver.install``."""

    version: str
    size_bytes: int


class ToolDriver(Protocol):
    """Per-install-method driver.

    Implementations receive ``root`` which is the per-tool subdirectory under
    the overlay (e.g., ``/home/asdd/.asdd-tools/claude/``). They must stage
    new installs at ``root/incoming/<ver>/`` and atomically rename to
    ``root/versions/<ver>/`` on success.
    """

    method: str

    def installed_version(self, tool: ManagedTool, root: Path) -> str | None: ...
    def latest_version(self, tool: ManagedTool, *, timeout: float) -> str | None: ...
    def install(self, tool: ManagedTool, root: Path, version: str) -> InstallResult: ...
    def uninstall(self, tool: ManagedTool, root: Path, version: str) -> None: ...


# ---------------------------------------------------------------------------
# Driver dispatch
# ---------------------------------------------------------------------------


def driver_for(tool: ManagedTool) -> ToolDriver:
    """Return the driver implementing ``tool.driver_method``."""
    if tool.driver_method == "npm-global":
        return NpmGlobalDriver()
    if tool.driver_method == "github-release":
        return GithubReleaseDriver()
    if tool.driver_method == "astral-install":
        return AstralInstallDriver()
    raise DriverError(f"no driver registered for method {tool.driver_method!r}")


# ---------------------------------------------------------------------------
# Helpers shared across drivers
# ---------------------------------------------------------------------------


def _http_get_json(url: str, *, timeout: float) -> dict | None:
    """GET ``url`` with timeout; return parsed JSON or None on any failure.

    The whole point of the upstream version check is graceful degradation —
    when anything goes wrong we return None and the caller renders
    "could not check" without surfacing a stack trace.
    """
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "asdd/spec-002",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError, ConnectionError, OSError):
        return None


def _atomic_rename(src: Path, dst: Path) -> None:
    """``os.replace`` from src to dst — atomic on POSIX file systems."""
    os.replace(src, dst)


def _dir_size_bytes(path: Path) -> int:
    """Recursive size of a directory, in bytes. Used for manifest history."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def retarget_bin_symlink(overlay_root: Path, tool: ManagedTool, version: str) -> None:
    """Update ``<overlay_root>/bin/<binary>`` to point at the new version.

    The per-tool root holds ``versions/<ver>/...``; the aggregate ``bin/`` at
    the overlay root is what ``PATH`` actually resolves through. We update
    the symlink atomically: create a new symlink at a temporary name, then
    ``os.replace`` over the existing one.
    """
    bin_dir = overlay_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / tool.binary_name
    new_target_relpath = _relative_binary_path(tool, version)
    tmp = bin_dir / f".{tool.binary_name}.new"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(new_target_relpath, tmp)
    _atomic_rename(tmp, target)


def _relative_binary_path(tool: ManagedTool, version: str) -> str:
    """Return the symlink target relative to the aggregate ``bin/`` directory.

    The shape depends on the driver. ``npm-global`` and ``github-release``
    put the binary at ``versions/<ver>/bin/<binary>``; ``astral-install``
    puts it directly at ``versions/<ver>/<binary>``.
    """
    if tool.driver_method == "astral-install":
        return f"../{tool.name}/versions/{version}/{tool.binary_name}"
    return f"../{tool.name}/versions/{version}/bin/{tool.binary_name}"


# ---------------------------------------------------------------------------
# Driver: npm-global (claude)
# ---------------------------------------------------------------------------


class NpmGlobalDriver:
    """Install via ``npm install -g --prefix=<root>`` inside the container."""

    method = "npm-global"

    def __init__(self, *, container_runner: "_ContainerRunner | None" = None) -> None:
        # Injectable for tests; default runs through `docker exec`.
        self._runner = container_runner or _DockerExecRunner()

    def installed_version(self, tool: ManagedTool, root: Path) -> str | None:
        # Resolve the symlink under root/../bin/<binary> via the aggregate;
        # but drivers operate per-tool — we read the symlink at root/../bin/<binary>
        # if it exists, else fall back to scanning versions/.
        aggregate_bin = root.parent / "bin" / tool.binary_name
        if aggregate_bin.is_symlink():
            target = os.readlink(aggregate_bin)
            # target is "../<tool>/versions/<ver>/bin/<binary>"
            parts = target.split("/")
            try:
                idx = parts.index("versions")
                return parts[idx + 1]
            except (ValueError, IndexError):
                return None
        return None

    def latest_version(self, tool: ManagedTool, *, timeout: float) -> str | None:
        url = f"https://registry.npmjs.org/-/package/{tool.source_id}/dist-tags"
        data = _http_get_json(url, timeout=timeout)
        if not data:
            return None
        return data.get("latest")

    def install(self, tool: ManagedTool, root: Path, version: str) -> InstallResult:
        incoming = root / "incoming" / version
        if incoming.exists():
            shutil.rmtree(incoming)
        incoming.mkdir(parents=True, exist_ok=True)

        container_root = self._container_path_for(root)
        container_incoming = f"{container_root}/incoming/{version}"
        spec = f"{tool.source_id}@{version}"
        cmd = ["npm", "install", "-g", f"--prefix={container_incoming}", spec]
        result = self._runner.run(cmd)
        if result.returncode != 0:
            shutil.rmtree(incoming, ignore_errors=True)
            raise DriverError(
                f"npm install failed for {spec} (exit {result.returncode}): "
                f"{result.stderr[:200] if result.stderr else ''}"
            )

        target = root / "versions" / version
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_rename(incoming, target)
        size = _dir_size_bytes(target)
        return InstallResult(version=version, size_bytes=size)

    def uninstall(self, tool: ManagedTool, root: Path, version: str) -> None:
        target = root / "versions" / version
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)

    @staticmethod
    def _container_path_for(host_path: Path) -> str:
        """Map a host path under the overlay to the container's mount point."""
        host_path = host_path.resolve()
        # Find the per-project root: $ASDD_HOME/_state/tools/<project>/<tool>
        # and replace everything up to <tool> with ASDD_OVERLAY_MOUNT.
        parts = host_path.parts
        try:
            tools_idx = parts.index("tools")
            # parts[tools_idx+1] is the project_id; parts[tools_idx+2:] is the
            # path inside the per-project overlay.
            inside = "/".join(parts[tools_idx + 2 :])
            return f"{ASDD_OVERLAY_MOUNT}/{inside}"
        except ValueError:
            # Should not happen in normal flow; fall through to the raw path.
            return str(host_path)


# ---------------------------------------------------------------------------
# Driver: github-release (gh) — implemented in Phase 8; stub for MVP
# ---------------------------------------------------------------------------


class GithubReleaseDriver:
    """Stub. Phase 8 will implement install/uninstall via tarball download."""

    method = "github-release"

    def installed_version(self, tool: ManagedTool, root: Path) -> str | None:
        return _read_symlinked_version(root, tool)

    def latest_version(self, tool: ManagedTool, *, timeout: float) -> str | None:
        url = f"https://api.github.com/repos/{tool.source_id}/releases/latest"
        data = _http_get_json(url, timeout=timeout)
        if not data:
            return None
        tag = data.get("tag_name", "")
        return tag.lstrip("v") or None

    def install(self, tool: ManagedTool, root: Path, version: str) -> InstallResult:
        raise DriverError("github-release driver not implemented yet (Phase 8)")

    def uninstall(self, tool: ManagedTool, root: Path, version: str) -> None:
        target = root / "versions" / version
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)


# ---------------------------------------------------------------------------
# Driver: astral-install (uv) — implemented in Phase 8; stub for MVP
# ---------------------------------------------------------------------------


class AstralInstallDriver:
    """Stub. Phase 8 will implement install/uninstall via GitHub release tarball."""

    method = "astral-install"

    def installed_version(self, tool: ManagedTool, root: Path) -> str | None:
        return _read_symlinked_version(root, tool)

    def latest_version(self, tool: ManagedTool, *, timeout: float) -> str | None:
        url = f"https://api.github.com/repos/{tool.source_id}/releases/latest"
        data = _http_get_json(url, timeout=timeout)
        if not data:
            return None
        tag = data.get("tag_name", "")
        return tag.lstrip("v") or None

    def install(self, tool: ManagedTool, root: Path, version: str) -> InstallResult:
        raise DriverError("astral-install driver not implemented yet (Phase 8)")

    def uninstall(self, tool: ManagedTool, root: Path, version: str) -> None:
        target = root / "versions" / version
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)


# ---------------------------------------------------------------------------
# Shared helper for reading "what version does the aggregate symlink point at?"
# ---------------------------------------------------------------------------


def _read_symlinked_version(root: Path, tool: ManagedTool) -> str | None:
    aggregate_bin = root.parent / "bin" / tool.binary_name
    if not aggregate_bin.is_symlink():
        return None
    target = os.readlink(aggregate_bin)
    parts = target.split("/")
    try:
        idx = parts.index("versions")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Baseline-version snapshot reader (used by cmd_versions when no overlay exists)
# ---------------------------------------------------------------------------


def read_baseline_version(container_name: str, tool_name: str) -> str | None:
    """Read ``/opt/asdd-baseline/versions/<tool>`` from the container.

    Returns None if the container isn't running or the file doesn't exist.
    """
    result = subprocess.run(
        [
            "docker",
            "exec",
            container_name,
            "cat",
            f"{ASDD_BASELINE_DIR}/versions/{tool_name}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


# ---------------------------------------------------------------------------
# Container runner abstraction (injectable for tests)
# ---------------------------------------------------------------------------


@dataclass
class _ProcessResult:
    returncode: int
    stdout: str
    stderr: str


class _ContainerRunner(Protocol):
    def run(self, cmd: list[str]) -> _ProcessResult: ...


class _DockerExecRunner:
    """Default runner: ``docker exec -u asdd <container> <cmd...>``."""

    def __init__(self, container_name: str = "") -> None:
        self.container_name = container_name

    def run(self, cmd: list[str]) -> _ProcessResult:
        if not self.container_name:
            # Convenience for unit tests that don't set a container — run on host.
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            return _ProcessResult(result.returncode, result.stdout, result.stderr)
        full = ["docker", "exec", "-u", "asdd", self.container_name, *cmd]
        result = subprocess.run(full, capture_output=True, text=True, check=False)
        return _ProcessResult(result.returncode, result.stdout, result.stderr)
