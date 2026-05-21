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
from typing import Literal

from asdd import auth

Mode = Literal["interactive", "autonomous", "persistent"]

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
    # ${ASDD_HOME}; when set, the subscription credential store is mounted
    # (spec 009). None preserves the legacy no-auth-mount behaviour used by
    # some tests.
    asdd_home: Path | None = None
    # When True (autonomous opt-in, spec 009 US4/FR-007), inject
    # ANTHROPIC_API_KEY and suppress the subscription store mount for this run.
    use_api_key: bool = False


class ProjectContainerError(RuntimeError):
    """Base error class for spec 008 container operations."""


class AlreadyRunningError(ProjectContainerError):
    """Raised when an operation requires the container to be stopped but it isn't."""

    def __init__(self, project_id: str, mode: str | None) -> None:
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


def auth_mounts(asdd_home: Path) -> list[tuple[str, str, str]]:
    """Mount tuples for the asdd-owned subscription credential store (spec 009).

    Maps the store's ``claude.json`` and ``claude/`` onto the in-container
    user's ``~/.claude.json`` and ``~/.claude/`` read-write, so the
    in-container Claude session reads, refreshes, and writes the login back
    to the one shared store (FR-002/FR-004/FR-005/FR-015). Used by every
    mode; replaces spec 008's interactive-only host ``~/.claude`` mount.
    """
    return [
        (
            str(auth.store_json_path(asdd_home)),
            f"{IN_CONTAINER_USER_HOME}/.claude.json",
            "rw",
        ),
        (
            str(auth.store_claude_dir(asdd_home)),
            f"{IN_CONTAINER_USER_HOME}/.claude",
            "rw",
        ),
    ]


def _compose_mounts(pc: ProjectContainer) -> list[tuple[str, str, str]]:
    """Mounts for a container: the workspace, plus the subscription store
    unless this is an API-key opt-in run (spec 009 FR-007)."""
    mounts = [(str(pc.workspace_path), IN_CONTAINER_WORKDIR, "rw")]
    if pc.asdd_home is not None and not pc.use_api_key:
        mounts += auth_mounts(pc.asdd_home)
    return mounts


def interactive_mounts(workspace_path: Path, asdd_home: Path | None = None) -> list[tuple[str, str, str]]:
    """Mount tuples for interactive mode: workspace + subscription store."""
    mounts = [(str(workspace_path), IN_CONTAINER_WORKDIR, "rw")]
    if asdd_home is not None:
        mounts += auth_mounts(asdd_home)
    return mounts


def autonomous_mounts(
    workspace_path: Path, asdd_home: Path | None = None, *, use_api_key: bool = False
) -> list[tuple[str, str, str]]:
    """Mount tuples for autonomous mode: workspace + subscription store
    (unless ``use_api_key`` — then workspace only and the key is injected)."""
    mounts = [(str(workspace_path), IN_CONTAINER_WORKDIR, "rw")]
    if asdd_home is not None and not use_api_key:
        mounts += auth_mounts(asdd_home)
    return mounts


def ensure_image_built(
    image: str = IMAGE_NAME,
    dockerfile: Path = DOCKERFILE_PATH,
    *,
    build_context: Path | None = None,
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


# ANTHROPIC_API_KEY is injected only on an explicit API-key opt-in run
# (spec 009 FR-007); by default every mode authenticates on the mounted
# subscription store instead. ASDD_JOB_STUB_OUTPUT is always propagated when
# set so integration tests get a deterministic result without a live LLM.
_API_KEY_ENV = "ANTHROPIC_API_KEY"
_STUB_OUTPUT_ENV = "ASDD_JOB_STUB_OUTPUT"


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
    mounts = _compose_mounts(pc)
    started_at = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Persistent sessions (spec 010) must outlive a detach and be
    # docker-start-able after a crash, so they omit --rm (the container
    # persists when stopped). Their lifecycle is owned by the host-side
    # launchd "babysitter" supervisor, not by a Docker restart policy —
    # OrbStack does not honour `--restart` on a killed container, so relying
    # on it would silently break crash recovery. Interactive/autonomous stay
    # ephemeral (--rm); their callers tear them down.
    lifecycle_flags: list[str] = [] if pc.mode == "persistent" else ["--rm"]

    cmd: list[str] = [
        "docker",
        "run",
        "-d",
        *lifecycle_flags,
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

    # Auth: by default the subscription store is mounted (see _compose_mounts)
    # and no API key is passed. Only an explicit opt-in run injects the key
    # (spec 009 FR-007). The stub-output var is always propagated when set so
    # integration tests stay deterministic without a live LLM.
    import os as _os

    if pc.use_api_key:
        value = _os.environ.get(_API_KEY_ENV)
        if value is not None:
            cmd += ["-e", f"{_API_KEY_ENV}={value}"]
    stub = _os.environ.get(_STUB_OUTPUT_ENV)
    if stub is not None:
        cmd += ["-e", f"{_STUB_OUTPUT_ENV}={stub}"]

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
    """True iff a container for this project is currently running (FR-002).

    Degrades to False when docker is unreachable or absent, so host-side
    callers (e.g. the persistent-session checks) don't crash on a machine
    without a daemon."""
    try:
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
    except OSError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def running_mode(project_id: str) -> str | None:
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


def attach_session(project_id: str) -> int:
    """Attach an interactive Claude session to a running container (spec 010).

    Runs ``claude --continue`` so the conversation resumes from the history
    persisted in the mounted ``~/.claude`` store — giving continuity across
    container restarts. Detaching ends only this exec; the container (and
    thus the persistent session) keeps running. Returns claude's exit code.
    """
    result = subprocess.run(
        ["docker", "exec", "-it", container_name(project_id), "claude", "--continue"],
        check=False,
    )
    return result.returncode


def restart_count(project_id: str) -> int | None:
    """Docker's restart count for the container, or None if not inspectable."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.RestartCount}}", container_name(project_id)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def state(project_id: str) -> str | None:
    """Container state string (e.g. 'running', 'exited'), or None if absent."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", container_name(project_id)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def is_persistent_running(project_id: str) -> bool:
    """True iff a persistent-mode container for this project is running (FR-013)."""
    return is_running(project_id) and running_mode(project_id) == "persistent"


def exists(project_id: str) -> bool:
    """True iff a container (any state) with this project's name exists."""
    return state(project_id) is not None


def start_existing(project_id: str) -> None:
    """`docker start` an existing (stopped) container. Raises on failure."""
    result = subprocess.run(
        ["docker", "start", container_name(project_id)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ProjectContainerError(
            f"docker start failed for project {project_id!r} (exit "
            f"{result.returncode}): {result.stderr.strip()}"
        )


def wait_container(project_id: str) -> int:
    """Block until the container stops; return its exit code (or -1 if the
    wait itself failed, e.g. the container no longer exists). Used by the
    launchd babysitter to hold the supervised session (spec 010)."""
    result = subprocess.run(
        ["docker", "wait", container_name(project_id)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return -1
    try:
        return int(result.stdout.strip())
    except ValueError:
        return -1


def run_interactive_login(asdd_home: Path) -> int:
    """Run an interactive ``claude`` login in a throwaway container with the
    subscription store mounted (spec 009 FR-001 fresh-login path).

    The operator completes Claude Code's normal login (URL + paste-code,
    which works without a browser in the container); credentials are written
    straight into the mounted store. Returns claude's exit code. ``--rm`` so
    nothing lingers.
    """
    cmd: list[str] = [
        "docker",
        "run",
        "--rm",
        "-it",
        "--name",
        f"{CONTAINER_PREFIX}login",
        "-w",
        IN_CONTAINER_USER_HOME,
    ]
    for host, container, mode in auth_mounts(asdd_home):
        cmd += ["-v", f"{host}:{container}:{mode}"]
    cmd += [IMAGE_NAME, "claude"]
    result = subprocess.run(cmd, check=False)
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


def remove_container(project_id: str, *, force: bool = False) -> bool:
    """Remove the (stopped) container by name. Idempotent.

    Persistent-mode containers run without ``--rm``, so a stopped one lingers
    and would collide with the next ``docker run --name``; ``serve``/``stop``
    use this to clear it. Returns True iff a container was removed.
    """
    args = ["docker", "rm"]
    if force:
        args.append("-f")
    args.append(container_name(project_id))
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode == 0:
        return True
    if "No such container" in result.stderr or "not found" in result.stderr.lower():
        return False
    raise ProjectContainerError(
        f"docker rm failed for project {project_id!r} (exit "
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
    "attach_session",
    "attach_shell",
    "auth_mounts",
    "autonomous_mounts",
    "exists",
    "is_persistent_running",
    "restart_count",
    "start_existing",
    "state",
    "wait_container",
    "container_name",
    "ensure_image_built",
    "interactive_mounts",
    "is_running",
    "list_running",
    "remove_container",
    "run_interactive_login",
    "running_mode",
    "start_container",
    "stop_container",
]
