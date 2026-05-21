"""Claude subscription credential store (spec 009).

asdd owns a single host-side copy of the operator's Claude Code
subscription credentials under ``${ASDD_HOME}/_state/claude-auth/``,
seeded from the operator's existing host login (or established by a fresh
in-container ``claude`` login). Every container mode bind-mounts this
store so interactive, autonomous-dispatch, and persistent runs all
authenticate on the operator's subscription rather than a metered API key.

This module is the single, mockable surface for the store: path helpers,
seed-from-host, status, clear, and an advisory lock. The bind-mounting
lives in :mod:`asdd.project_container`; the CLI commands live in
:mod:`asdd.bootstrap`.

Security (spec 009 FR-008/FR-009, constitution V): the store holds live
OAuth tokens. It lives outside any project workspace, is git-ignored,
excluded from archives and the deploy bundle, created ``0700``/``0600``,
and never logged. ``status`` returns metadata only — never token values.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

STORE_DIRNAME = "claude-auth"
CLAUDE_JSON = "claude.json"
CLAUDE_DIR = "claude"
# The file Claude Code writes when it uses file-based credentials (Linux
# containers, and macOS when the Keychain is unavailable). This — not the
# presence of claude.json — is the reliable "is there a real token" signal.
CREDENTIALS_FILE = ".credentials.json"
META_FILE = "asdd-auth-meta.json"
LOCK_FILE = ".lock"

SOURCE_SEEDED = "seeded-from-host"
SOURCE_FRESH = "fresh-login"


class AuthError(RuntimeError):
    """User-facing credential-store failure with a clear message."""


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def store_dir(asdd_home: Path) -> Path:
    return Path(asdd_home) / "_state" / STORE_DIRNAME


def store_json_path(asdd_home: Path) -> Path:
    return store_dir(asdd_home) / CLAUDE_JSON


def store_claude_dir(asdd_home: Path) -> Path:
    return store_dir(asdd_home) / CLAUDE_DIR


def meta_path(asdd_home: Path) -> Path:
    return store_dir(asdd_home) / META_FILE


def credentials_file(asdd_home: Path) -> Path:
    return store_claude_dir(asdd_home) / CREDENTIALS_FILE


def host_claude_json() -> Path:
    return Path.home() / ".claude.json"


def host_claude_dir() -> Path:
    return Path.home() / ".claude"


def host_login_present() -> bool:
    """True iff the operator already has a Claude Code login on this host."""
    return host_claude_json().is_file()


def has_credential(asdd_home: Path) -> bool:
    """True iff the store holds a *real* file-based credential.

    Keyed on ``claude/.credentials.json`` (non-trivial), not on the presence
    of ``claude.json`` — the latter is config that exists even when the token
    lives in the macOS Keychain (i.e. when seed-from-host carried config but
    no usable token).
    """
    cf = credentials_file(asdd_home)
    try:
        return cf.is_file() and cf.stat().st_size > 2
    except OSError:
        return False


def is_logged_in(asdd_home: Path) -> bool:
    """True iff a usable subscription credential is present (see has_credential)."""
    return has_credential(asdd_home)


# ---------------------------------------------------------------------------
# Store mutation (guard with store_lock at the call site)
# ---------------------------------------------------------------------------


def _ensure_store(asdd_home: Path) -> Path:
    d = store_dir(asdd_home)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def _write_meta(asdd_home: Path, *, source: str) -> None:
    payload = {
        "source": source,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    p = meta_path(asdd_home)
    p.write_text(json.dumps(payload, indent=2) + "\n")
    os.chmod(p, 0o600)


def seed_from_host(asdd_home: Path) -> None:
    """Copy the operator's host Claude login into the asdd-owned store (FR-014).

    Raises ``AuthError`` if no host login is present.
    """
    if not host_login_present():
        raise AuthError(
            "no host Claude login found at ~/.claude.json; "
            "run `asdd login --fresh` to log in inside a container"
        )
    _ensure_store(asdd_home)

    dst_json = store_json_path(asdd_home)
    dst_json.write_bytes(host_claude_json().read_bytes())
    os.chmod(dst_json, 0o600)

    dst_dir = store_claude_dir(asdd_home)
    if dst_dir.exists():
        _rmtree(dst_dir)
    src_dir = host_claude_dir()
    if src_dir.is_dir():
        _copytree(src_dir, dst_dir)
        os.chmod(dst_dir, 0o700)

    _write_meta(asdd_home, source=SOURCE_SEEDED)


def prepare_empty_store(asdd_home: Path) -> None:
    """Create empty store files so a container can bind-mount them for a
    fresh in-container login (the login writes credentials into the mount)."""
    _ensure_store(asdd_home)
    j = store_json_path(asdd_home)
    if not j.exists():
        j.write_text("{}\n")
        os.chmod(j, 0o600)
    d = store_claude_dir(asdd_home)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)


def mark_fresh_login(asdd_home: Path) -> None:
    """Record that the store was established by a fresh in-container login."""
    if not is_logged_in(asdd_home):
        raise AuthError(
            "login did not produce credentials; the in-container `claude` "
            "login may have been cancelled"
        )
    _write_meta(asdd_home, source=SOURCE_FRESH)


def ensure_workspace_trusted(asdd_home: Path, workdir: str) -> None:
    """Pre-accept Claude Code's workspace-trust dialog for ``workdir`` (spec 010).

    A persistent session starts an *interactive* ``claude`` unattended (launchd
    babysitter, no human at the keyboard). Claude shows a one-time "trust this
    folder?" prompt on first launch in a directory, which would block that
    start. We record acceptance for the in-container workspace path in the
    store's ``claude.json`` (the file mounted at the container's
    ``~/.claude.json``) so the prompt never appears. Idempotent; merges into
    whatever config already exists rather than clobbering it.
    """
    p = store_json_path(asdd_home)
    try:
        data = json.loads(p.read_text()) if p.is_file() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    projects = data.get("projects")
    if not isinstance(projects, dict):
        projects = {}
        data["projects"] = projects
    entry = projects.get(workdir)
    if not isinstance(entry, dict):
        entry = {}
        projects[workdir] = entry
    entry["hasTrustDialogAccepted"] = True

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(p, 0o600)


def clear(asdd_home: Path) -> bool:
    """Remove the credential store. Idempotent; returns True iff it existed."""
    d = store_dir(asdd_home)
    if not d.exists():
        return False
    _rmtree(d)
    return True


# ---------------------------------------------------------------------------
# Status (metadata only — never token values)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthStatus:
    logged_in: bool
    source: str | None = None
    identity: str | None = None
    expiry: str | None = None


def status(asdd_home: Path) -> AuthStatus:
    """Derive auth status from the store on disk — no network call (FR-011/R5)."""
    if not is_logged_in(asdd_home):
        return AuthStatus(logged_in=False)

    source: str | None = None
    mp = meta_path(asdd_home)
    if mp.is_file():
        try:
            source = json.loads(mp.read_text()).get("source")
        except (OSError, json.JSONDecodeError):
            source = None

    identity, expiry = _read_identity_expiry(asdd_home)
    return AuthStatus(logged_in=True, source=source, identity=identity, expiry=expiry)


def _read_identity_expiry(asdd_home: Path) -> tuple[str | None, str | None]:
    """Best-effort: surface an account label and token expiry *if* the
    credential file exposes them. Never raises; returns (None, None) when the
    shape is unknown. We do not assume Claude Code's private schema — we look
    for any key whose name contains 'email' / 'expire'."""
    try:
        data = json.loads(store_json_path(asdd_home).read_text())
    except (OSError, json.JSONDecodeError):
        return (None, None)
    identity = _find_value_by_key_substring(data, "email")
    expiry = _find_value_by_key_substring(data, "expire")
    return (identity, expiry)


def _find_value_by_key_substring(obj: object, needle: str, *, depth: int = 4) -> str | None:
    if depth < 0:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if needle in str(k).lower() and isinstance(v, (str, int)):
                return str(v)
        for v in obj.values():
            found = _find_value_by_key_substring(v, needle, depth=depth - 1)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_value_by_key_substring(v, needle, depth=depth - 1)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------------------
# Advisory lock (guards seed / clear against concurrent structural mutation)
# ---------------------------------------------------------------------------


def _lock_path(asdd_home: Path) -> Path:
    # Lock lives beside the store, not inside it, so acquiring the lock does
    # not recreate a cleared store (keeps `clear`/logout idempotent).
    d = store_dir(asdd_home)
    d.parent.mkdir(parents=True, exist_ok=True)
    return d.parent / f"{STORE_DIRNAME}{LOCK_FILE}"


@contextmanager
def store_lock(asdd_home: Path) -> Iterator[None]:
    """Exclusive advisory lock guarding structural store mutation (FR-010, R2)."""
    import fcntl

    lock = _lock_path(asdd_home)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


# ---------------------------------------------------------------------------
# Internal fs helpers (kept local so the module has no third-party deps)
# ---------------------------------------------------------------------------


def _copytree(src: Path, dst: Path) -> None:
    import shutil

    shutil.copytree(src, dst)


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path)


__all__ = [
    "AuthError",
    "AuthStatus",
    "clear",
    "credentials_file",
    "ensure_workspace_trusted",
    "has_credential",
    "host_login_present",
    "is_logged_in",
    "mark_fresh_login",
    "meta_path",
    "prepare_empty_store",
    "seed_from_host",
    "status",
    "store_claude_dir",
    "store_dir",
    "store_json_path",
    "store_lock",
]
