"""Integration test for spec 007 US6 — per-project secret isolation (T058).

Asserts:
- US6.1: agent A's container env contains A's secrets, not B's.
- US6.2: encrypted at rest (no plaintext in the workspace files).
- US6.3: archived projects' secrets are not loaded into any future env.

Two layers of gating:
- @pytest.mark.docker — skipped when no daemon (CI).
- skipif on `sops` AND age key presence — the test does a real
  SOPS+age round-trip, which needs both the binary and an age keypair.
  In environments without those, the test skips with a clear reason.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from asdd import bootstrap, project_container, secrets


def _have_sops_and_age_key() -> tuple[bool, str]:
    """Return (ok, skip_reason) for the SOPS+age round-trip preconditions."""
    if shutil.which("sops") is None:
        return False, "sops binary not on PATH"
    age_key_file = os.environ.get("SOPS_AGE_KEY_FILE")
    if not age_key_file or not Path(age_key_file).is_file():
        return False, (
            "SOPS_AGE_KEY_FILE not set or file missing — generate an age "
            "keypair (`age-keygen -o ~/.config/age/keys.txt`) and export "
            "SOPS_AGE_KEY_FILE=$HOME/.config/age/keys.txt + "
            "SOPS_AGE_RECIPIENTS=$(grep '^# public key' that file)"
        )
    if not os.environ.get("SOPS_AGE_RECIPIENTS"):
        return False, "SOPS_AGE_RECIPIENTS not set"
    return True, ""


_OK, _SKIP_REASON = _have_sops_and_age_key()


pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not _OK, reason=_SKIP_REASON or "preconditions missing"),
]


def _container_env(project_id: str, key: str) -> str | None:
    """Read one env var from the running container's environment."""
    result = subprocess.run(
        [
            "docker",
            "exec",
            project_container.container_name(project_id),
            "printenv",
            key,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def test_us6_1_secrets_scoped_per_project(
    asdd_home_with_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project A's container sees A's secrets but not B's."""
    # Register a second project so cross-project queries are meaningful.
    bootstrap.cmd_new(
        asdd_home=asdd_home_with_project,
        project_id="other-proj",
        description="for US6 isolation test",
    )

    # Add distinct secrets to each project.
    bootstrap.cmd_secrets_add(
        asdd_home=asdd_home_with_project,
        project_id="vaultcontrol",
        key="A_SECRET",
        value="alpha",
    )
    bootstrap.cmd_secrets_add(
        asdd_home=asdd_home_with_project,
        project_id="other-proj",
        key="B_SECRET",
        value="beta",
    )

    project_container.ensure_image_built()
    # Open project A's container in the background (start_container handles secret injection).
    pc_a = project_container.ProjectContainer(
        project_id="vaultcontrol",
        mode="interactive",
        workspace_path=asdd_home_with_project / "projects" / "vaultcontrol",
    )
    secrets_a = bootstrap._decrypt_project_secrets(
        next(
            r
            for r in bootstrap._read_registry_raw(asdd_home_with_project)["projects"]
            if r["id"] == "vaultcontrol"
        )
    )
    project_container.start_container(pc_a, extra_env=secrets_a)
    try:
        assert _container_env("vaultcontrol", "A_SECRET") == "alpha"
        # B's secret is NOT in A's container.
        assert _container_env("vaultcontrol", "B_SECRET") is None
    finally:
        project_container.stop_container("vaultcontrol")


def test_us6_2_secrets_encrypted_at_rest(asdd_home_with_project: Path) -> None:
    """The on-disk secrets file contains ENC[...] markers, never plaintext."""
    bootstrap.cmd_secrets_add(
        asdd_home=asdd_home_with_project,
        project_id="vaultcontrol",
        key="GITHUB_TOKEN",
        value="ghp_super_secret_pat_value",
    )
    secrets_path = (
        asdd_home_with_project
        / "projects"
        / "vaultcontrol"
        / "_state"
        / "secrets.enc.yml"
    )
    contents = secrets_path.read_text()
    assert "ENC[" in contents, "secret value should be SOPS-encrypted on disk"
    assert "ghp_super_secret_pat_value" not in contents, (
        "plaintext leaked into encrypted file"
    )


def test_us6_3_archived_project_secrets_not_loaded(
    asdd_home_with_project: Path,
) -> None:
    """Archiving a project must make its secrets unreadable by the decrypt path."""
    bootstrap.cmd_secrets_add(
        asdd_home=asdd_home_with_project,
        project_id="vaultcontrol",
        key="ARCHIVED_SECRET",
        value="should-vanish",
    )
    # Flip the registry row to archived directly to avoid the snapshot path.
    import yaml as _yaml

    reg_path = asdd_home_with_project / "_state" / "projects.yml"
    raw = _yaml.safe_load(reg_path.read_text())
    for r in raw["projects"]:
        if r["id"] == "vaultcontrol":
            r["lifecycle_state"] = "archived"
    reg_path.write_text(_yaml.safe_dump(raw, sort_keys=False))

    # Now decrypt_project should refuse for this project.
    row = next(
        r
        for r in bootstrap._read_registry_raw(asdd_home_with_project)["projects"]
        if r["id"] == "vaultcontrol"
    )
    proj = bootstrap._registry_row_as_project(row)
    with pytest.raises(secrets.ProjectArchivedError):
        secrets.decrypt_project(proj)
