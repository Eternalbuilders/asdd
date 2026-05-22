"""Project workspace scaffolding.

Lays down the on-disk layout for a new ASDD project:

  1. ``.specify/`` — installed by invoking Spec Kit's own ``specify init``
     via ``uvx`` (or ``uv tool run``). This is the same mechanism the
     operator would run manually, so the resulting tree is byte-compatible
     with what Claude Code expects for slash-command discovery
     (``/speckit-specify``, ``/speckit-plan``, etc.). Earlier versions of
     this module copied a hand-curated template directory and ran into
     subtle registration gaps; delegating to upstream removes that class
     of bug entirely.

  2. ``.specify/memory/constitution.md`` — replaced with an ASDD-flavoured
     starter (Spec Kit's default constitution is too generic).

  3. ``inbox/ schedule/ jobs/ results/ _state/`` — the spec-001 queue
     directories the kernel polls.

  4. ``specs/`` — the first ``/speckit-specify`` invocation fills this.

Idempotent: re-running on an already-scaffolded workspace is a no-op.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


# Directories created empty under the workspace; per spec-001 queue layout.
_QUEUE_DIRS = ("inbox", "schedule", "jobs", "results", "_state")

# Spec Kit's Git source. The repo is not tagged on a stable cadence today;
# main is the canonical reference. If reproducibility becomes critical we
# can pin a commit SHA here without changing the rest of the flow.
_SPECIFY_SOURCE = "git+https://github.com/github/spec-kit.git"


class SpecifyInitError(RuntimeError):
    """``specify init`` failed (uvx missing, network down, schema clash, etc.)."""


def _have_uvx() -> bool:
    return shutil.which("uvx") is not None


def _run_specify_init(workspace_path: Path) -> None:
    """Invoke ``uvx ... specify init . --here ...`` inside ``workspace_path``.

    Uses ``--ignore-agent-tools`` so the call does not error out when the
    Claude Code CLI is not on PATH (which is the common case inside the
    kernel container, and harmless from the operator container since we
    never resolve commands during init).
    """
    if not _have_uvx():
        raise SpecifyInitError(
            "uvx is not on PATH; install uv (https://astral.sh/uv) so "
            "Spec Kit can scaffold the project (`pip install uv` or "
            "`brew install uv`)"
        )

    cmd = [
        "uvx",
        "--from",
        _SPECIFY_SOURCE,
        "specify",
        "init",
        ".",
        "--here",
        "--force",
        "--integration",
        "claude",
        "--script",
        "sh",
        "--ignore-agent-tools",
    ]
    log.info("running: %s (cwd=%s)", " ".join(cmd), workspace_path)
    try:
        subprocess.run(
            cmd,
            check=True,
            cwd=workspace_path,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise SpecifyInitError(
            f"specify init failed (exit {e.returncode}):\n"
            f"--- stdout ---\n{e.stdout}\n--- stderr ---\n{e.stderr}"
        ) from e


def scaffold(workspace_path: Path, *, templates_root: Path) -> None:
    """Lay down the standard ASDD project layout at ``workspace_path``.

    Args:
        workspace_path: target directory; created if missing.
        templates_root: directory containing ``constitution-starter.md``
            (usually ``${ASDD_HOME}/_templates/`` or the repo's
            ``project_skeleton/``). The ``.specify/`` subtree is no longer
            read from here — Spec Kit installs it.
    """
    workspace_path.mkdir(parents=True, exist_ok=True)

    # 1. .specify/ — installed by Spec Kit itself (idempotent: skip if present).
    dst_specify = workspace_path / ".specify"
    if not dst_specify.exists():
        _run_specify_init(workspace_path)
        log.info("scaffolded .specify/ at %s via specify init", dst_specify)
    if not dst_specify.is_dir():
        raise SpecifyInitError(
            f"specify init did not create .specify/ at {dst_specify}"
        )

    # 2. Replace Spec Kit's default constitution with our ASDD starter.
    src_const = templates_root / "constitution-starter.md"
    dst_const = dst_specify / "memory" / "constitution.md"
    if not src_const.is_file():
        raise FileNotFoundError(
            f"templates_root missing constitution-starter.md: {src_const}"
        )
    dst_const.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_const, dst_const)
    log.info("scaffolded constitution at %s", dst_const)

    # 3. Empty queue dirs.
    for d in _QUEUE_DIRS:
        _ensure_dir(workspace_path / d)

    # 4. specs/ directory (empty — first /speckit-specify fills it).
    _ensure_dir(workspace_path / "specs")


def _ensure_dir(path: Path) -> None:
    """`mkdir -p` that tolerates an entry the cloned remote already provides.

    `Path.mkdir(exist_ok=True)` still raises ``FileExistsError`` when the path
    exists as a *non-directory*. The case that bites here: a cloned repo whose
    ``specs`` is a symlink to an external store (e.g. a spec vault) that does
    not exist on this host — a dangling symlink. Such an entry can't serve as
    the scaffold directory, so we replace it with a real one. A symlink that
    resolves, or an existing real dir/file, is left untouched.
    """
    if path.is_symlink():
        if path.exists():  # resolves to a real target — leave the clone's link
            return
        path.unlink()  # dangling — drop it so we can create a usable dir
    elif path.exists():
        return
    path.mkdir(parents=True, exist_ok=True)


__all__ = ["SpecifyInitError", "scaffold"]
