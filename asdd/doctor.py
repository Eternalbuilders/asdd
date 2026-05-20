"""Tooling-baseline check (T016).

Per FR-024, a project is considered healthy only if its workspace contains
the minimum baseline: a Spec Kit installation, a project constitution, and
a Git repository. Failure to meet the baseline transitions the project to
``unhealthy`` in the registry overlay.

The check is pure: it returns reasons but does not mutate the registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asdd.registry import Project


def check_baseline(project: Project) -> list[str]:
    """Return a list of human-readable failure reasons.

    An empty list means the project is healthy.
    """
    reasons: list[str] = []
    ws = project.workspace

    if not ws.exists():
        return [f"workspace path does not exist: {ws}"]
    if not ws.is_dir():
        return [f"workspace path is not a directory: {ws}"]

    if not (ws / ".specify").is_dir():
        reasons.append("missing .specify/ directory (Spec Kit not installed)")

    if not (ws / ".specify" / "memory" / "constitution.md").is_file():
        reasons.append("missing .specify/memory/constitution.md (project constitution)")

    # Accept either a .git directory (regular repo) or a .git file (worktree)
    git_path = ws / ".git"
    if not git_path.exists():
        reasons.append("missing .git/ (not a Git repository)")

    return reasons


__all__ = ["check_baseline"]
