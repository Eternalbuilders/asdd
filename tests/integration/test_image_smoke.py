"""Image-level smoke tests for feature 001.

These exercise the built ``asdd/project:latest`` image directly via
``docker run``. They are gated by ``@pytest.mark.docker`` so the dev
container (no docker socket) skips them cleanly.

What this test asserts, mapped to feature 001 requirements:

- FR-007/FR-008/SC-003: when ``ASDD_PROJECT_ID`` is set, an interactive
  shell's ``$PS1`` includes ``(<project>)``.
- FR-010 (no leakage): when ``ASDD_PROJECT_ID`` is unset, the prompt
  has no parenthesized prefix.
- FR-011/FR-012/SC-004: ``gh`` is on ``$PATH`` and reports a version
  consistent with the Dockerfile's pinned ``GH_VERSION`` (currently 2.94).
"""

from __future__ import annotations

import subprocess

import pytest

from asdd import project_container as pc

pytestmark = pytest.mark.docker


def _docker_run(*extra: str) -> subprocess.CompletedProcess[str]:
    """Run a one-shot command inside the image. ``--rm`` so we leave no
    trace. Uses ``pc.IMAGE_NAME`` so we stay in sync with the rest of asdd."""
    return subprocess.run(
        ["docker", "run", "--rm", *extra, pc.IMAGE_NAME, "bash", "-lic", _command(extra)],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _command(_: tuple[str, ...]) -> str:
    # `bash -lic` expects the script as the next arg; tests below pass it
    # via a different `docker run` shape (see below). This helper exists
    # so we can keep _docker_run() flexible.
    return 'echo "$PS1"'


def _ensure_image_built() -> None:
    """If the image isn't built yet, build it. Mirrors what asdd does."""
    pc.ensure_image_built()


def test_prompt_includes_project_id_when_env_set() -> None:
    """FR-007/FR-008: the in-container interactive shell shows `(<id>)`."""
    _ensure_image_built()
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-e",
            "ASDD_PROJECT_ID=my-app",
            pc.IMAGE_NAME,
            "bash",
            "-lic",
            'echo "PS1=[${PS1}]"',
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "(my-app)" in proc.stdout, proc.stdout


def test_prompt_unchanged_when_env_unset() -> None:
    """FR-010 (no leakage): without ASDD_PROJECT_ID the prefix is absent."""
    _ensure_image_built()
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            pc.IMAGE_NAME,
            "bash",
            "-lic",
            'echo "PS1=[${PS1}]"',
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    # No parenthesized prefix should appear before the user@host portion.
    # We assert the literal substring '(' is not in the PS1 marker section.
    line = next(
        (line for line in proc.stdout.splitlines() if line.startswith("PS1=[")),
        "",
    )
    assert "(" not in line, f"unexpected prefix in PS1: {line}"


def test_gh_is_preinstalled() -> None:
    """FR-011/SC-004: `gh --version` exits 0 and reports a 2.94.x version."""
    _ensure_image_built()
    proc = subprocess.run(
        ["docker", "run", "--rm", pc.IMAGE_NAME, "gh", "--version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    # The Dockerfile pin is 2.94.x; if the pin is bumped later, update this
    # assertion in the same commit so the smoke stays meaningful.
    assert "gh version 2.94." in proc.stdout, proc.stdout
