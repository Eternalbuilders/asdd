"""Host-side supervisor for persistent project sessions (spec 010).

A persistent session (``asdd serve <id>``) is kept alive by two cooperating
layers (research R1):

1. The container's Docker restart policy (``--restart unless-stopped``)
   handles crash / daemon-restart / reboot of the container itself.
2. A **launchd agent** with ``RunAtLoad=true`` re-runs the idempotent
   ``asdd serve <id>`` at login, covering the case where the container was
   removed or Docker starts only after the operator logs in.

This module owns layer 2: generating the launchd property list and
loading/unloading it via ``launchctl``. Per constitution IV the supervisor
is host-side only — nothing here runs inside the container, and this is the
sanctioned "host-side launchd shim" exception. The plist contains only the
``asdd serve <id>`` command — no secrets.

macOS-specific by design; a future always-on Linux host would swap launchd
for systemd behind this same surface.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABEL_PREFIX = "com.asdd.session."


class SupervisorError(RuntimeError):
    """Host-side supervision failure with an actionable message."""


def agent_label(project_id: str) -> str:
    return f"{LABEL_PREFIX}{project_id}"


def agent_path(project_id: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{agent_label(project_id)}.plist"


# launchd relaunch throttle (seconds). Bounds crash-loops so a session that
# can't start (e.g. revoked credentials) doesn't hammer the host (FR-012).
THROTTLE_INTERVAL = 10


def asdd_program_args(project_id: str) -> list[str]:
    """Absolute argv launchd runs as the foreground "babysitter".

    ``asdd serve <id> --supervise`` ensures the container is up and then
    blocks until it exits; when it returns, launchd (``KeepAlive``) relaunches
    it — that is what actually restarts a crashed session. Prefers the
    installed ``asdd`` console script; falls back to the module so it works
    from launchd's minimal environment.
    """
    asdd = shutil.which("asdd")
    if asdd:
        return [asdd, "serve", project_id, "--supervise"]
    return [
        os.path.abspath(sys.executable),
        "-m",
        "asdd.bootstrap",
        "serve",
        project_id,
        "--supervise",
    ]


def render_plist(
    project_id: str,
    program_args: list[str] | None = None,
    environ: dict[str, str] | None = None,
) -> bytes:
    """Return the launchd plist bytes for this project's supervisor agent.

    The agent IS the supervisor: ``KeepAlive`` relaunches the foreground
    babysitter whenever it exits (i.e. when the container dies), and
    ``RunAtLoad`` starts it at login/reboot. ``ThrottleInterval`` bounds the
    relaunch rate so an unstartable session can't tight-loop (FR-012). This
    replaces reliance on Docker's restart policy, which OrbStack does not
    honour for killed containers.
    """
    args = program_args or asdd_program_args(project_id)
    label = agent_label(project_id)
    log_path = str(Path.home() / "Library" / "Logs" / f"{label}.log")
    plist: dict[str, object] = {
        "Label": label,
        "ProgramArguments": args,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": THROTTLE_INTERVAL,
        "ProcessType": "Background",
        # Route babysitter stdout+stderr to ~/Library/Logs for diagnostics.
        "StandardOutPath": log_path,
        "StandardErrorPath": log_path,
    }
    if environ:
        # launchd runs with a minimal environment; pin what the babysitter
        # needs (ASDD_HOME, PATH) so it uses the same home `serve` did.
        plist["EnvironmentVariables"] = dict(environ)
    return plistlib.dumps(plist)


def is_installed(project_id: str) -> bool:
    return agent_path(project_id).is_file()


def _launchctl(args: list[str], *, allow_fail: bool = False) -> None:
    try:
        result = subprocess.run(["launchctl", *args], capture_output=True, text=True)
    except FileNotFoundError as e:
        raise SupervisorError(
            "launchctl not found; the persistent-session supervisor requires "
            "macOS (launchd)"
        ) from e
    if result.returncode != 0 and not allow_fail:
        raise SupervisorError(
            f"launchctl {' '.join(args)} failed: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


def install(
    project_id: str,
    *,
    program_args: list[str] | None = None,
    environ: dict[str, str] | None = None,
) -> Path:
    """Write and load the launchd agent (idempotent). Returns the plist path."""
    path = agent_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_plist(project_id, program_args, environ))

    # Re-load cleanly: bootout any stale instance first (benign if absent),
    # then bootstrap; fall back to load -w on older macOS.
    domain = f"gui/{os.getuid()}"
    _launchctl(["bootout", f"{domain}/{agent_label(project_id)}"], allow_fail=True)
    boot = subprocess.run(
        ["launchctl", "bootstrap", domain, str(path)],
        capture_output=True,
        text=True,
    )
    if boot.returncode != 0:
        # Older macOS path.
        _launchctl(["load", "-w", str(path)])
    return path


def uninstall(project_id: str) -> bool:
    """Unload and remove the launchd agent (idempotent).

    Returns True iff an agent file existed. Unloading happens before file
    removal so a deliberate stop wins over any in-flight relaunch.
    """
    path = agent_path(project_id)
    label = agent_label(project_id)
    domain = f"gui/{os.getuid()}"
    _launchctl(["bootout", f"{domain}/{label}"], allow_fail=True)
    if path.is_file():
        _launchctl(["unload", "-w", str(path)], allow_fail=True)
        path.unlink()
        return True
    return False


__all__ = [
    "LABEL_PREFIX",
    "SupervisorError",
    "agent_label",
    "agent_path",
    "asdd_program_args",
    "install",
    "is_installed",
    "render_plist",
    "uninstall",
]
