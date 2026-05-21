"""Unit tests for spec 009 bootstrap commands that need no docker.

cmd_login (seed path), cmd_logout, cmd_whoami, and the dispatch/open
fail-fast-when-not-logged-in guard (the guard runs before any container op).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from asdd import auth, bootstrap


@pytest.fixture
def fake_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Host with a portable (file-based) Claude login."""
    host = tmp_path / "host-home"
    host.mkdir()
    (host / ".claude.json").write_text(json.dumps({"email": "x@y.z"}))
    cdir = host / ".claude"
    cdir.mkdir()
    (cdir / ".credentials.json").write_text(json.dumps({"accessToken": "tok"}))
    monkeypatch.setenv("HOME", str(host))
    return host


@pytest.fixture
def config_only_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Host with Claude config but no portable credential file to copy."""
    host = tmp_path / "cfg-home"
    (host / ".claude").mkdir(parents=True)
    (host / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "m@x.z"}}))
    monkeypatch.setenv("HOME", str(host))
    return host


def test_cmd_login_seeds_from_host(fake_host: Path, asdd_home: Path) -> None:
    source = bootstrap.cmd_login(asdd_home=asdd_home)
    assert source == auth.SOURCE_SEEDED
    assert auth.is_logged_in(asdd_home)


def test_cmd_login_config_only_directs_to_fresh(
    config_only_host: Path, asdd_home: Path
) -> None:
    """Seed finds config but no portable credential → clear error, no half-store."""
    with pytest.raises(bootstrap.BootstrapError, match="no portable credential"):
        bootstrap.cmd_login(asdd_home=asdd_home)
    assert auth.is_logged_in(asdd_home) is False
    assert auth.store_dir(asdd_home).exists() is False


def test_cmd_logout_clears(fake_host: Path, asdd_home: Path) -> None:
    bootstrap.cmd_login(asdd_home=asdd_home)
    assert bootstrap.cmd_logout(asdd_home=asdd_home) is True
    assert auth.is_logged_in(asdd_home) is False
    # idempotent
    assert bootstrap.cmd_logout(asdd_home=asdd_home) is False


def test_cmd_whoami_reflects_state(fake_host: Path, asdd_home: Path) -> None:
    assert bootstrap.cmd_whoami(asdd_home=asdd_home).logged_in is False
    bootstrap.cmd_login(asdd_home=asdd_home)
    st = bootstrap.cmd_whoami(asdd_home=asdd_home)
    assert st.logged_in is True
    assert st.source == auth.SOURCE_SEEDED


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("Error: 401 Unauthorized", "re-login required"),
        ("OAuth token expired, please log in", "re-login required"),
        ("rate limit exceeded (429)", "usage limit reached"),
        ("usage limit reached for this window", "usage limit reached"),
        ("some unrelated traceback", "job failed"),
    ],
)
def test_classify_job_failure(detail: str, expected: str) -> None:
    assert expected in bootstrap._classify_job_failure(detail)


def test_dispatch_fails_fast_when_not_logged_in(asdd_home_with_project: Path) -> None:
    """US2 AS3: dispatch with no subscription login fails fast (before docker)."""
    ws = asdd_home_with_project / "projects" / "vaultcontrol"
    (ws / "inbox").mkdir(parents=True, exist_ok=True)
    job = ws / "inbox" / "job.md"
    job.write_text("# job\n")
    with pytest.raises(bootstrap.BootstrapError, match="no subscription login"):
        bootstrap.cmd_dispatch(
            asdd_home=asdd_home_with_project, project_id="vaultcontrol", job_path=job
        )
