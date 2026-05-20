"""Migration 002 — stamp project_id on legacy job/result notes (T067).

For pre-spec-007 vaults: every note under ``<vault>/{jobs,results}/`` that
lacks a top-level ``project_id`` frontmatter field is rewritten with
``project_id: vaultcontrol`` (or whatever ``--project-id`` is passed).
Idempotent: notes that already have the field are skipped.

Usage:
    python -m asdd.migrations.m002_stamp_project_id_on_legacy_notes \\
        /path/to/projects/vaultcontrol [--project-id vaultcontrol] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# We avoid kernel.parsers.frontmatter to keep this script importable
# without the full kernel package on sys.path. Use a minimal YAML-frontmatter
# parser that round-trips faithfully.

_FRONTMATTER_DELIM = "---"


def _split_frontmatter(text: str) -> tuple[str, str] | None:
    """Return (frontmatter_yaml, body) or None if no frontmatter."""
    if not text.startswith(_FRONTMATTER_DELIM):
        return None
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FRONTMATTER_DELIM:
            fm = "".join(lines[1:i])
            body = "".join(lines[i + 1 :])
            return fm, body
    return None


def _stamp_one(path: Path, project_id: str, *, dry_run: bool) -> bool:
    """Return True if the file was (or would be) modified."""
    text = path.read_text()
    split = _split_frontmatter(text)
    if split is None:
        # No frontmatter — leave alone (probably not a note we care about)
        return False
    fm, body = split

    # Detect existing top-level project_id field (whitespace-tolerant)
    for line in fm.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("project_id:"):
            return False  # already stamped

    new_fm = f"project_id: {project_id}\n" + fm
    new_text = f"{_FRONTMATTER_DELIM}\n{new_fm}{_FRONTMATTER_DELIM}\n{body}"
    if not dry_run:
        # Atomic write-temp-then-rename
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(new_text)
        tmp.replace(path)
    return True


def run(
    workspace_root: Path,
    *,
    project_id: str = "vaultcontrol",
    dry_run: bool = False,
) -> dict:
    """Walk jobs/ and results/ under workspace_root and stamp project_id."""
    modified = 0
    skipped = 0
    visited = 0
    for sub in ("jobs", "results"):
        d = workspace_root / sub
        if not d.is_dir():
            continue
        for path in d.rglob("*.md"):
            visited += 1
            if _stamp_one(path, project_id, dry_run=dry_run):
                modified += 1
            else:
                skipped += 1
    return {
        "workspace": str(workspace_root),
        "project_id": project_id,
        "visited": visited,
        "modified": modified,
        "skipped": skipped,
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stamp project_id on legacy notes.")
    p.add_argument("workspace", type=Path, help="path to a project workspace")
    p.add_argument("--project-id", default="vaultcontrol")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    report = run(args.workspace, project_id=args.project_id, dry_run=args.dry_run)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
