"""Spec 006: the project skeleton ships Claude Code permission guardrails.

`project_skeleton/.claude/settings.json` must carry deny-rules that block the
destructive git operations the constitution forbids (force-push, hard reset,
rebase, hook-skipping commits). Deny rules are enforced even when containers run
in `auto` permission mode, so this file is the deterministic safety floor.

See specs/006-container-auto-permission-mode/contracts/permission-settings.md.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKELETON_SETTINGS = REPO_ROOT / "project_skeleton" / ".claude" / "settings.json"

# The deny rules the contract guarantees are present.
REQUIRED_DENY = {
    "Bash(git push --force *)",
    "Bash(git push -f *)",
    "Bash(git push * --force*)",
    "Bash(git * --force*)",
    "Bash(git *force*)",
    "Bash(git reset --hard *)",
    "Bash(git rebase *)",
    "Bash(git commit * --no-verify *)",
    "Bash(git commit *-n *)",
}


def test_skeleton_settings_is_valid_json() -> None:
    data = json.loads(SKELETON_SETTINGS.read_text())
    assert isinstance(data, dict)


def test_skeleton_settings_denies_destructive_git() -> None:
    data = json.loads(SKELETON_SETTINGS.read_text())
    deny = set(data.get("permissions", {}).get("deny", []))
    missing = REQUIRED_DENY - deny
    assert not missing, f"skeleton settings.json missing deny rules: {sorted(missing)}"


def test_skeleton_settings_has_no_project_level_default_mode() -> None:
    """`defaultMode` is ignored in project settings by Claude Code; auto mode is
    enabled via the launch flag instead. Guard against re-introducing it here."""
    data = json.loads(SKELETON_SETTINGS.read_text())
    assert "defaultMode" not in data.get("permissions", {})
