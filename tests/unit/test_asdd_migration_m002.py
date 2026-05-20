"""Unit test for migration 002 — stamp project_id on legacy notes (T067)."""

from __future__ import annotations

from pathlib import Path

from asdd.migrations.m002_stamp_project_id_on_legacy_notes import run


def test_stamps_legacy_notes(tmp_path: Path) -> None:
    ws = tmp_path / "vaultcontrol"
    (ws / "jobs").mkdir(parents=True)
    (ws / "results" / "2026-05-13").mkdir(parents=True)

    legacy_job = ws / "jobs" / "20260513T120000Z-abc12345.md"
    legacy_job.write_text(
        "---\n"
        "job_id: 20260513T120000Z-abc12345\n"
        "status: done\n"
        "agent: agent-test\n"
        "---\n"
        "body text\n"
    )
    legacy_result = ws / "results" / "2026-05-13" / "result.md"
    legacy_result.write_text(
        "---\n"
        "job_id: 20260513T120000Z-abc12345\n"
        "agent: agent-test\n"
        "ts_utc: 2026-05-13T12:00:00Z\n"
        "---\n"
        "result body\n"
    )

    report = run(ws, project_id="vaultcontrol")
    assert report["modified"] == 2
    assert report["skipped"] == 0
    assert report["visited"] == 2

    # Re-running is idempotent
    report2 = run(ws, project_id="vaultcontrol")
    assert report2["modified"] == 0
    assert report2["skipped"] == 2

    # Verify the stamped content
    job_text = legacy_job.read_text()
    assert job_text.startswith("---\nproject_id: vaultcontrol\n")
    assert "job_id: 20260513T120000Z-abc12345" in job_text
    assert job_text.endswith("body text\n")


def test_dry_run_does_not_modify(tmp_path: Path) -> None:
    ws = tmp_path / "vaultcontrol"
    (ws / "jobs").mkdir(parents=True)
    p = ws / "jobs" / "j.md"
    p.write_text("---\njob_id: x\n---\nbody\n")
    before = p.read_text()

    report = run(ws, project_id="vaultcontrol", dry_run=True)
    assert report["modified"] == 1
    assert p.read_text() == before


def test_ignores_files_without_frontmatter(tmp_path: Path) -> None:
    ws = tmp_path / "vaultcontrol"
    (ws / "jobs").mkdir(parents=True)
    (ws / "jobs" / "notes.md").write_text("just markdown, no yaml\n")
    report = run(ws, project_id="vaultcontrol")
    assert report["modified"] == 0
    assert report["skipped"] == 1
