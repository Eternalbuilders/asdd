"""Unit tests for asdd/secrets.py routing logic (T028).

Tests routing of secrets to env vs tmpfs and the archived-project guard.
SOPS round-trip is NOT tested here (requires age keypair + sops binary);
that path is exercised by the US6 integration test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from asdd.registry import Project
from asdd.secrets import (
    ProjectArchivedError,
    decrypt_project,
    env_pairs,
    tmpfs_pairs,
)


def _proj(state: str = "active") -> Project:
    return Project(
        id="t",
        name="T",
        workspace_path="/tmp/nonexistent",
        git_remote=None,
        default_branch="main",
        lifecycle_state=state,
        created_at="2026-05-14T00:00:00Z",
        last_checked_at="2026-05-14T00:00:00Z",
        description=None,
    )


def test_env_pairs_picks_short_scalars() -> None:
    secrets = {
        "GITHUB_TOKEN": "ghp_abc",
        "OPENAI_API_KEY": "sk-xyz",
    }
    assert env_pairs(secrets) == secrets
    assert tmpfs_pairs(secrets) == {}


def test_tmpfs_pairs_picks_multiline_values() -> None:
    secrets = {
        "GITHUB_TOKEN": "ghp_abc",
        "PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----\n",
    }
    e = env_pairs(secrets)
    t = tmpfs_pairs(secrets)
    assert e == {"GITHUB_TOKEN": "ghp_abc"}
    assert t == {"PRIVATE_KEY": "/run/secrets/PRIVATE_KEY"}


def test_tmpfs_pairs_routes_long_values() -> None:
    # 600-char single-line value exceeds the 512-byte env threshold
    long_val = "x" * 600
    secrets = {"BIG": long_val, "small": "ok"}
    assert env_pairs(secrets) == {"small": "ok"}
    assert tmpfs_pairs(secrets) == {"BIG": "/run/secrets/BIG"}


def test_decrypt_project_returns_empty_when_no_file(tmp_path: Path) -> None:
    proj = Project(
        id="t",
        name="T",
        workspace_path=str(tmp_path),
        git_remote=None,
        default_branch="main",
        lifecycle_state="active",
        created_at="2026-05-14T00:00:00Z",
        last_checked_at="2026-05-14T00:00:00Z",
        description=None,
    )
    # No _state/secrets.enc.yml present → empty mapping, no sops invocation
    assert decrypt_project(proj) == {}


def test_decrypt_project_refuses_archived(tmp_path: Path) -> None:
    secrets_file = tmp_path / "_state" / "secrets.enc.yml"
    secrets_file.parent.mkdir(parents=True)
    secrets_file.write_text("encrypted: stuff\n")  # never actually read
    proj = Project(
        id="t",
        name="T",
        workspace_path=str(tmp_path),
        git_remote=None,
        default_branch="main",
        lifecycle_state="archived",
        created_at="2026-05-14T00:00:00Z",
        last_checked_at="2026-05-14T00:00:00Z",
        description=None,
    )
    with pytest.raises(ProjectArchivedError):
        decrypt_project(proj)


def test_workspace_doctor_baseline(tmp_path: Path) -> None:
    """Quick smoke for asdd.doctor.check_baseline."""
    from asdd.doctor import check_baseline

    proj_path = tmp_path / "proj"
    proj_path.mkdir()
    proj = Project(
        id="t",
        name="T",
        workspace_path=str(proj_path),
        git_remote=None,
        default_branch="main",
        lifecycle_state="active",
        created_at="2026-05-14T00:00:00Z",
        last_checked_at="2026-05-14T00:00:00Z",
        description=None,
    )
    reasons = check_baseline(proj)
    assert len(reasons) == 3  # missing .specify/, constitution, .git

    # Lay down the baseline
    (proj_path / ".specify" / "memory").mkdir(parents=True)
    (proj_path / ".specify" / "memory" / "constitution.md").write_text("# const\n")
    (proj_path / ".git").mkdir()
    assert check_baseline(proj) == []
