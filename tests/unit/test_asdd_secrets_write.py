"""Unit tests for the write surface of asdd/secrets.py (T059, T060).

Covers add_secret/remove_secret/list_keys with subprocess mocked. Real
SOPS round-trip (requires an age keypair on disk) is exercised by the
US6 integration test instead.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from asdd import secrets
from asdd.secrets import (
    SecretsConfigError,
    SopsEncryptError,
    add_secret,
    list_keys,
    remove_secret,
)


def _fake_run(rc: int, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.returncode = rc
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------- add_secret ----------------


def test_add_secret_first_time_requires_recipient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No file yet + no recipient → SecretsConfigError; no subprocess called."""
    monkeypatch.delenv("SOPS_AGE_RECIPIENTS", raising=False)
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: calls.append(a) or _fake_run(0))
    with pytest.raises(SecretsConfigError, match="age recipient"):
        add_secret(tmp_path, "API_KEY", "secret-value")
    assert calls == []


def test_add_secret_first_time_uses_env_recipient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First-time call with SOPS_AGE_RECIPIENTS set invokes sops -e --age <rcpt>."""
    monkeypatch.setenv("SOPS_AGE_RECIPIENTS", "age1example")
    captured: list[list[str]] = []

    def fake_run(cmd, **kw):
        captured.append(cmd)
        return _fake_run(0, stdout="encrypted-yaml-here\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    add_secret(tmp_path, "API_KEY", "secret-value")

    assert len(captured) == 1
    cmd = captured[0]
    assert cmd[:2] == ["sops", "-e"]
    assert "--age" in cmd and "age1example" in cmd
    # The encrypted output landed at the right path.
    assert (tmp_path / "_state" / "secrets.enc.yml").is_file()
    assert (tmp_path / "_state" / "secrets.enc.yml").read_text() == "encrypted-yaml-here\n"


def test_add_secret_first_time_explicit_recipient_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOPS_AGE_RECIPIENTS", "age1fromenv")
    captured: list[list[str]] = []

    def fake_run(cmd, **kw):
        captured.append(cmd)
        return _fake_run(0, stdout="x")

    monkeypatch.setattr(subprocess, "run", fake_run)
    add_secret(tmp_path, "K", "V", recipient="age1explicit")
    cmd = captured[0]
    assert "age1explicit" in cmd
    assert "age1fromenv" not in cmd


def test_add_secret_existing_file_uses_sops_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the file exists, sops --set is used (no recipient flag needed)."""
    secrets_file = tmp_path / "_state" / "secrets.enc.yml"
    secrets_file.parent.mkdir(parents=True)
    secrets_file.write_text("existing: ENC[...]\nsops: {}\n")
    captured: list[list[str]] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: (captured.append(cmd), _fake_run(0))[1],
    )
    add_secret(tmp_path, "NEW_KEY", "new-value")
    assert captured[0][:2] == ["sops", "--set"]
    assert '["NEW_KEY"] "new-value"' in captured[0]


def test_add_secret_propagates_sops_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOPS_AGE_RECIPIENTS", "age1x")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: _fake_run(1, stderr="sops: bad recipient"),
    )
    with pytest.raises(SopsEncryptError, match="bad recipient"):
        add_secret(tmp_path, "K", "V")


# ---------------- remove_secret ----------------


def test_remove_secret_returns_false_when_file_missing(tmp_path: Path) -> None:
    assert remove_secret(tmp_path, "ANY") is False


def test_remove_secret_invokes_sops_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets_file = tmp_path / "_state" / "secrets.enc.yml"
    secrets_file.parent.mkdir(parents=True)
    secrets_file.write_text("k: ENC[...]\n")
    captured: list[list[str]] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: (captured.append(cmd), _fake_run(0))[1],
    )
    assert remove_secret(tmp_path, "k") is True
    assert captured[0][:2] == ["sops", "--unset"]
    assert '["k"]' in captured[0]


def test_remove_secret_returns_false_when_key_not_in_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "_state").mkdir()
    (tmp_path / "_state" / "secrets.enc.yml").write_text("x: ENC[...]\n")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: _fake_run(1, stderr="Key not found in store"),
    )
    assert remove_secret(tmp_path, "missing") is False


def test_remove_secret_raises_on_real_sops_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "_state").mkdir()
    (tmp_path / "_state" / "secrets.enc.yml").write_text("x: ENC[...]\n")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: _fake_run(1, stderr="cannot read age key"),
    )
    with pytest.raises(SopsEncryptError, match="cannot read age key"):
        remove_secret(tmp_path, "x")


# ---------------- list_keys ----------------


def test_list_keys_empty_when_file_missing(tmp_path: Path) -> None:
    assert list_keys(tmp_path) == []


def test_list_keys_returns_top_level_keys_excluding_sops_metadata(tmp_path: Path) -> None:
    state = tmp_path / "_state"
    state.mkdir()
    (state / "secrets.enc.yml").write_text(
        "GITHUB_TOKEN: ENC[...]\n"
        "OPENAI_KEY: ENC[...]\n"
        "sops:\n"
        "    kms: []\n"
        "    age:\n"
        "    - recipient: age1example\n"
    )
    keys = list_keys(tmp_path)
    assert set(keys) == {"GITHUB_TOKEN", "OPENAI_KEY"}
    assert "sops" not in keys


def test_list_keys_never_decrypts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """list_keys must not invoke sops at all (otherwise a missing age key
    would falsely fail the listing operation)."""
    state = tmp_path / "_state"
    state.mkdir()
    (state / "secrets.enc.yml").write_text("FOO: ENC[...]\n")
    sentinel: list[str] = []
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: sentinel.append("invoked") or _fake_run(0)
    )
    list_keys(tmp_path)
    assert sentinel == [], "list_keys must not call sops"
