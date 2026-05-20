"""Per-project container lifecycle helpers (spec 008).

Thin Python wrapper around `docker run` / `docker exec` / `docker ps` /
`docker stop` so the host-side glue in `asdd.bootstrap` (cmd_open,
cmd_close, cmd_ps, future cmd_dispatch) has a single, mockable surface.

All functions shell out via `subprocess.run`. Unit tests in
`tests/unit/test_project_container.py` exercise argument shape with
the subprocess module mocked; integration tests in
`tests/integration/test_open_us1_us2_us3.py` exercise the real docker
daemon (gated by `@pytest.mark.docker`).
"""

from __future__ import annotations

import datetime as _dt
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

Mode = Literal["interactive", "autonomous"]

IMAGE_NAME = "asdd/project:latest"
CONTAINER_PREFIX = "asdd-project-"

# Repo root is wherever the installed `asdd` package's parent directory is —
# resolves correctly regardless of the caller's cwd, since `asdd open` is meant
# to be runnable from anywhere on the operator's host.
_PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = _PACKAGE_ROOT.parent
DOCKERFILE_PATH = REPO_ROOT / "docker" / "Dockerfile.project"

# Inside the container, the workspace lands here and bash starts here.
IN_CONTAINER_WORKDIR = "/asdd_home"
IN_CONTAINER_USER_HOME = "/home/asdd"


@dataclass(frozen=True)
class ProjectContainer:
    """In-memory representation of one project's container instance."""

    project_id: str
    mode: Mode
    workspace_path: Path
    image: str = IMAGE_NAME


class ProjectContainerError(RuntimeError):
    """Base error class for spec 008 container operations."""


class AlreadyRunningError(ProjectContainerError):
    """Raised when an operation requires the container to be stopped but it isn't."""

    def __init__(self, project_id: str, mode: Optional[str]) -> None:
        self.project_id = project_id
        self.mode = mode
        if mode == "autonomous":
            msg = (
                f"project {project_id!r} is currently processing a "
                "kernel-dispatched job; retry in a few seconds"
            )
        elif mode == "interactive":
            msg = (
                f"project {project_id!r} is already open in another shell; "
                f"attach with `docker exec -it {container_name(project_id)} bash` "
                f"or run `asdd close {project_id}` first"
            )
        else:
            msg = f"project {project_id!r} has a container already running"
        super().__init__(msg)


def container_name(project_id: str) -> str:
    """Container name from project id. One name per project (FR-002)."""
    return f"{CONTAINER_PREFIX}{project_id}"


def interactive_mounts(workspace_path: Path) -> list[tuple[str, str, str]]:
    """Mount tuples (host_path, container_path, mode) for interactive mode.

    Three mounts: the project workspace, the operator's Claude Code
    directory, and the operator's Claude Code sibling config file. The
    auth mounts are precisely what spec 008 FR-005 names as the
    permitted host-filesystem exception.
    """
    home = Path.home()
    return [
        (str(workspace_path), IN_CONTAINER_WORKDIR, "rw"),
        (str(home / ".claude"), f"{IN_CONTAINER_USER_HOME}/.claude", "rw"),
        (str(home / ".claude.json"), f"{IN_CONTAINER_USER_HOME}/.claude.json", "rw"),
    ]


def autonomous_mounts(workspace_path: Path) -> list[tuple[str, str, str]]:
    """Mount tuples for autonomous mode — workspace only, no operator creds (FR-009)."""
    return [(str(workspace_path), IN_CONTAINER_WORKDIR, "rw")]


def ensure_image_built(
    image: str = IMAGE_NAME,
    dockerfile: Path = DOCKERFILE_PATH,
    *,
    build_context: Optional[Path] = None,
) -> None:
    """Build the image if it isn't already present locally (FR-012).

    Runs `docker image inspect <image>`. On success returns silently.
    On failure (image absent), runs `docker build -f <dockerfile> -t
    <image> <build_context>`, streaming output to the operator's
    terminal so the wait isn't silent.

    Both ``dockerfile`` and ``build_context`` are derived from the
    installed asdd package's location (``REPO_ROOT``), not the caller's
    cwd — so `asdd open` works from anywhere on the operator's host.

    Raises ``ProjectContainerError`` if the dockerfile is missing or the
    build itself fails.
    """
    if not Path(dockerfile).is_file():
        raise ProjectContainerError(
            f"Dockerfile not found at {dockerfile}; "
            f"the asdd install at {REPO_ROOT} appears incomplete or stale "
            "— run `git pull` in the repo and re-install asdd"
        )

    inspect = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
    )
    if inspect.returncode == 0:
        return

    ctx = build_context or REPO_ROOT
    # Stream build output — don't capture, let it flow to the operator's TTY.
    proc = subprocess.run(
        ["docker", "build", "-f", str(dockerfile), "-t", image, str(ctx)],
    )
    if proc.returncode != 0:
        raise ProjectContainerError(
            f"docker build failed for {image} (exit {proc.returncode}); "
            f"see streamed output above"
        )


# Environment variables propagated from host into the container in
# autonomous mode. ANTHROPIC_API_KEY is the substitute for the
# interactive-mode `~/.claude/` bind mount (FR-009: autonomous mode must
# not see operator host credentials). ASDD_JOB_STUB_OUTPUT exists for
# integration tests that need a deterministic result without a live LLM.
_AUTONOMOUS_PASSTHROUGH_ENV = ("ANTHROPIC_API_KEY", "ASDD_JOB_STUB_OUTPUT")


def start_container(
    pc: ProjectContainer,
    *,
    extra_env: dict[str, str] | None = None,
) -> str:
    """Start the project container detached; return the container id (FR-001/FR-009).

    ``extra_env`` — when set, each key/value is injected via ``docker run -e``.
    Used by the dispatcher to pass decrypted project secrets (spec 007 US6
    via the spec 008 amendment: decrypted on host, injected at container
    start; no per-dispatch tmpfs).
    """
    mounts = (
        interactive_mounts(pc.workspace_path)
        if pc.mode == "interactive"
        else autonomous_mounts(pc.workspace_path)
    )
    started_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    cmd: list[str] = [
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        container_name(pc.project_id),
        "--label",
        f"asdd.project_id={pc.project_id}",
        "--label",
        f"asdd.mode={pc.mode}",
        "--label",
        f"asdd.started_at={started_at}",
        "-w",
        IN_CONTAINER_WORKDIR,
    ]
    for host, container, mode in mounts:
        cmd += ["-v", f"{host}:{container}:{mode}"]

    # Autonomous-mode auth: propagate ANTHROPIC_API_KEY (and a test-only
    # stub env var) from host into the container. Interactive mode uses
    # the bind-mounted ~/.claude/ directory instead, so no env-var
    # propagation is needed there.
    import os as _os

    if pc.mode == "autonomous":
        for name in _AUTONOMOUS_PASSTHROUGH_ENV:
            value = _os.environ.get(name)
            if value is not None:
                cmd += ["-e", f"{name}={value}"]

    # Project secrets — decrypted by the caller, passed here. Applied to
    # both interactive and autonomous modes (the operator's interactive
    # shell sees their own project's secrets; the autonomous agent
    # likewise).
    if extra_env:
        for name, value in extra_env.items():
            cmd += ["-e", f"{name}={value}"]

    cmd += [pc.image, "sleep", "infinity"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ProjectContainerError(
            f"docker run failed for project {pc.project_id!r} (exit "
            f"{result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.strip()


def is_running(project_id: str) -> bool:
    """True iff a container for this project is currently running (FR-002)."""
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            f"name=^{container_name(project_id)}$",
            "--format",
            "{{.ID}}",
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def running_mode(project_id: str) -> Optional[str]:
    """Mode label of a running container, or None if not running."""
    result = subprocess.run(
        [
            "docker",
            "inspect",
            "--format",
            '{{ index .Config.Labels "asdd.mode" }}',
            container_name(project_id),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    mode = result.stdout.strip()
    return mode or None


def assert_not_running(project_id: str) -> None:
    """Guard for cmd_open / cmd_dispatch — refuse-fast per A3."""
    if is_running(project_id):
        raise AlreadyRunningError(project_id, mode=running_mode(project_id))


def attach_shell(project_id: str) -> int:
    """Drop the operator into a bash shell inside the container (FR-003).

    Does NOT capture output — interactive TTY only. Returns bash's exit code.
    """
    result = subprocess.run(
        ["docker", "exec", "-it", container_name(project_id), "bash"],
        check=False,
    )
    return result.returncode


def stop_container(project_id: str, *, timeout: int = 10) -> bool:
    """Stop the project container if running. Idempotent.

    Returns True iff the container existed and was stopped; False if it
    was already gone. Errors other than "no such container" propagate.
    """
    result = subprocess.run(
        ["docker", "stop", "--time", str(timeout), container_name(project_id)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    # docker stop returns non-zero with "No such container" when already gone.
    if "No such container" in result.stderr or "not found" in result.stderr.lower():
        return False
    raise ProjectContainerError(
        f"docker stop failed for project {project_id!r} (exit "
        f"{result.returncode}): {result.stderr.strip()}"
    )


def list_running() -> list[dict[str, str]]:
    """List rows from `docker ps` of project containers (`asdd ps`).

    Returns a list of dicts with keys: ``project_id``, ``mode``,
    ``started_at``, ``name``. Empty list if none are running. Returns
    empty list (not an error) if docker is unreachable, so `asdd ps`
    degrades gracefully on hosts without a daemon.
    """
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            "label=asdd.project_id",
            "--format",
            '{{.Names}}\t{{.Label "asdd.project_id"}}\t'
            '{{.Label "asdd.mode"}}\t{{.Label "asdd.started_at"}}',
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    rows: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        name, project_id, mode, started_at = parts[0], parts[1], parts[2], parts[3]
        rows.append(
            {
                "name": name,
                "project_id": project_id,
                "mode": mode,
                "started_at": started_at,
            }
        )
    return rows


__all__ = [
    "AlreadyRunningError",
    "IMAGE_NAME",
    "Mode",
    "ProjectContainer",
    "ProjectContainerError",
    "assert_not_running",
    "attach_shell",
    "autonomous_mounts",
    "container_name",
    "ensure_image_built",
    "interactive_mounts",
    "is_running",
    "list_running",
    "running_mode",
    "start_container",
    "stop_container",
]
