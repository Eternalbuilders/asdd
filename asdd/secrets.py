"""Per-project secret decryption + injection (T014; US6 spec 007).

Reads ``<workspace>/_state/secrets.enc.yml`` via the vendored ``sops``
binary, returns the decrypted mapping in memory only. Spec 008 amended
the *injection* path (no more per-dispatch tmpfs); the project
container now reads decrypted values from its own env at start-time.

Two read strategies are still exposed for backward compatibility with
the spec-001/002 dispatcher contract (the legacy kernel still calls
``env_pairs``/``tmpfs_pairs``):

* ``env_pairs(secrets)`` — short scalars (API keys, tokens) for env.
* ``tmpfs_pairs(secrets)`` — multi-line / sensitive values for tmpfs.

Spec 008's project-container dispatcher uses ``decrypt_project`` and
passes the whole map via ``docker run -e``; tmpfs is no longer
constructed per-dispatch.

Write surface (spec 007 US6 T059/T060):

* ``add_secret(workspace, key, value, recipient=None)``
* ``remove_secret(workspace, key)``
* ``list_keys(workspace) -> list[str]`` — key list without decryption.

Decrypted plaintext never touches disk on either side. ``add_secret``
pipes plaintext via stdin to ``sops``; ``remove_secret`` uses
``sops --unset`` which operates on the encrypted file in place.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from asdd.registry import Project

log = logging.getLogger(__name__)


class SopsNotInstalledError(RuntimeError):
    """The vendored ``sops`` binary is not on PATH."""


class SopsDecryptError(RuntimeError):
    """sops refused to decrypt the file (missing key, bad signature, etc.)."""


class SopsEncryptError(RuntimeError):
    """sops failed to encrypt (no recipient configured, etc.)."""


class ProjectArchivedError(RuntimeError):
    """Attempted to decrypt secrets for a project in ``archived`` state."""


class SecretsConfigError(RuntimeError):
    """Operator-fixable mistake in the secrets setup (e.g., no recipient)."""


# Short scalars go to env vars; anything containing a newline or above this
# size threshold goes to a tmpfs file. The threshold is conservative; env
# vars work up to ~128KB on Linux but anything that could contain a private
# key block (PEM, age key) belongs on disk via tmpfs.
_ENV_MAX_LEN = 512


def _secrets_path(project: Project) -> Path:
    return project.workspace / "_state" / "secrets.enc.yml"


def decrypt_project(project: Project) -> dict[str, str]:
    """Decrypt the project's secrets via ``sops``; return the mapping.

    Returns an empty mapping if the project has no secrets file. Raises if
    sops fails or the project is archived.
    """
    if project.lifecycle_state == "archived":
        raise ProjectArchivedError(
            f"refusing to decrypt secrets for archived project {project.id!r}"
        )

    path = _secrets_path(project)
    if not path.exists():
        return {}

    try:
        result = subprocess.run(
            ["sops", "-d", "--output-type", "json", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise SopsNotInstalledError(
            "sops binary not found on PATH; required by per-project secret decryption"
        ) from e
    except subprocess.CalledProcessError as e:
        raise SopsDecryptError(f"sops failed to decrypt {path}: {e.stderr.strip()}") from e

    try:
        decoded = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise SopsDecryptError(f"sops output not valid JSON: {e}") from e

    if not isinstance(decoded, dict):
        raise SopsDecryptError("sops output must be a JSON object at the top level")

    # Coerce values to strings; reject non-string values so we don't smuggle
    # binary or unicode-unstable data through env vars.
    result_map: dict[str, str] = {}
    for k, v in decoded.items():
        if not isinstance(k, str):
            raise SopsDecryptError(f"secret key not a string: {k!r}")
        if not isinstance(v, str):
            raise SopsDecryptError(f"secret {k!r}: value must be a string, got {type(v).__name__}")
        result_map[k] = v
    return result_map


def _is_short_scalar(value: str) -> bool:
    return "\n" not in value and len(value) <= _ENV_MAX_LEN


def env_pairs(secrets: dict[str, str]) -> dict[str, str]:
    """Return the subset of ``secrets`` that should be injected via env vars."""
    return {k: v for k, v in secrets.items() if _is_short_scalar(v)}


def tmpfs_pairs(secrets: dict[str, str]) -> dict[str, str]:
    """Return the subset that should be injected via tmpfs files.

    Mapping is key → in-container path under ``/run/secrets/``.
    """
    return {k: f"/run/secrets/{k}" for k, v in secrets.items() if not _is_short_scalar(v)}


def _ensure_state_dir(workspace_path: Path) -> Path:
    state = workspace_path / "_state"
    state.mkdir(parents=True, exist_ok=True)
    return state / "secrets.enc.yml"


def _resolve_recipient(explicit: str | None = None) -> str:
    """Find the age recipient for first-time encryption.

    Resolution order:
      1. ``explicit`` argument
      2. ``SOPS_AGE_RECIPIENTS`` env var (matches sops' own resolution)

    Raises ``SecretsConfigError`` with a helpful message if neither is set.
    """
    if explicit:
        return explicit
    env_val = os.environ.get("SOPS_AGE_RECIPIENTS")
    if env_val:
        return env_val
    raise SecretsConfigError(
        "no age recipient configured for first-time secret encryption; "
        "set SOPS_AGE_RECIPIENTS=age1... in the environment or pass "
        "recipient= explicitly"
    )


def add_secret(
    workspace_path: Path,
    key: str,
    value: str,
    *,
    recipient: str | None = None,
) -> None:
    """Add or update one secret in the workspace's encrypted store.

    First-time call (file missing) requires an age recipient via the
    ``recipient`` arg or ``SOPS_AGE_RECIPIENTS`` env var. Subsequent
    calls re-use the existing file's recipient list — ``sops --set``
    preserves it.

    Plaintext only appears in the subprocess stdin (memory), never on
    disk.

    Raises:
      - ``SecretsConfigError`` if first-time encrypting without recipient
      - ``SopsEncryptError`` if sops returns non-zero
    """
    secrets_path = _ensure_state_dir(workspace_path)

    if secrets_path.exists():
        # File exists — preserve existing recipients via `sops --set`.
        result = subprocess.run(
            ["sops", "--set", f'["{key}"] "{value}"', str(secrets_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SopsEncryptError(
                f"sops --set failed for {secrets_path}: {result.stderr.strip()}"
            )
        return

    # First-time creation — need a recipient.
    age_recipient = _resolve_recipient(recipient)
    plaintext = yaml.safe_dump({key: value}, sort_keys=False)
    result = subprocess.run(
        [
            "sops",
            "-e",
            "--age",
            age_recipient,
            "--input-type",
            "yaml",
            "--output-type",
            "yaml",
            "/dev/stdin",
        ],
        input=plaintext,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SopsEncryptError(
            f"sops -e failed creating {secrets_path}: {result.stderr.strip()}"
        )
    secrets_path.write_text(result.stdout)


def remove_secret(workspace_path: Path, key: str) -> bool:
    """Remove one secret. Returns True if a key was removed, False if absent.

    Uses ``sops --unset`` which operates on the encrypted file in place
    (no plaintext ever lands on disk).
    """
    secrets_path = _ensure_state_dir(workspace_path)
    if not secrets_path.exists():
        return False

    # `sops --unset` returns non-zero if the key isn't present; distinguish
    # "absent" (return False, not an error) from "actual failure".
    result = subprocess.run(
        ["sops", "--unset", f'["{key}"]', str(secrets_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    err = result.stderr.lower()
    if "not found" in err or "no such" in err or "does not exist" in err:
        return False
    raise SopsEncryptError(
        f"sops --unset failed for key {key!r}: {result.stderr.strip()}"
    )


def list_keys(workspace_path: Path) -> list[str]:
    """List secret keys without decrypting any values.

    SOPS encrypts values but leaves YAML keys in cleartext, so we can
    parse the file and read the top-level key list. The ``sops:``
    metadata block (added by sops itself) is filtered out.

    Returns an empty list if the file doesn't exist.
    """
    secrets_path = workspace_path / "_state" / "secrets.enc.yml"
    if not secrets_path.exists():
        return []
    try:
        parsed = yaml.safe_load(secrets_path.read_text()) or {}
    except yaml.YAMLError as e:
        raise SopsDecryptError(
            f"secrets file at {secrets_path} is not valid YAML: {e}"
        ) from e
    if not isinstance(parsed, dict):
        return []
    return [k for k in parsed if k != "sops"]


__all__ = [
    "ProjectArchivedError",
    "SecretsConfigError",
    "SopsDecryptError",
    "SopsEncryptError",
    "SopsNotInstalledError",
    "add_secret",
    "decrypt_project",
    "env_pairs",
    "list_keys",
    "remove_secret",
    "tmpfs_pairs",
]
