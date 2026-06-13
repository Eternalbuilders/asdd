# Implementation Plan: Container Auto Permission Mode for Git

**Branch**: `006-container-auto-permission-mode` | **Date**: 2026-06-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-container-auto-permission-mode/spec.md`

## Summary

Today the three ways asdd starts Claude — persistent `asdd serve`, autonomous
`asdd dispatch`, and interactive `asdd claude` — launch the `claude` CLI with no
permission flag, so every git command waits on per-command approval. A separate
container that *was* started in Claude Code's `auto` permission mode runs git
frictionlessly (its harness reports "Allowed by auto mode classifier"). The
inconsistency is purely the launch mode, not a file.

The fix is two small, declarative changes:

1. **Start every launch path in `auto` permission mode** by adding
   `--permission-mode auto` to the four `claude` invocations across the three
   entrypoints (`asdd-session.sh` ×2, `asdd-run-job.sh` ×1, `attach_claude` ×1).
   In auto mode a classifier auto-approves routine commands, so git/`gh` run
   without prompting — uniformly, in every container.

2. **Bake deny-guards into each project** via a checked-in
   `project_skeleton/.claude/settings.json` carrying `permissions.deny` rules for
   the destructive git operations the constitution forbids (force-push, hard
   reset, rebase, `--no-verify`). Deny rules are enforced *before* the classifier
   even in auto mode, so they are a hard floor. The scaffolder
   (`asdd/workspace.py:scaffold`) writes this file into each new project's
   workspace; existing projects are backfilled by a documented step.

No new dependency, no new command surface, no change to auth or network posture.

## Technical Context

**Language/Version**: Bash (the two container entrypoint scripts); Python 3.12 (the `asdd` CLI scaffolder and tests); JSON (the permission settings file). No new Python code beyond a few lines in `workspace.py`.

**Primary Dependencies**: The Claude Code CLI's existing `--permission-mode auto` flag and its `permissions.deny` settings semantics. No new Python or system packages — preserves the three-deps invariant (PyYAML, jsonschema, click).

**Storage**: One committed `.claude/settings.json` per project workspace (and the canonical copy in `project_skeleton/`). It travels with the project repo.

**Testing**: pytest. Unit: (a) assert `asdd/workspace.py:scaffold` writes `<workspace>/.claude/settings.json` with the expected deny rules (new test, mirrors existing `tests/unit/test_workspace*.py`); (b) assert the entrypoint scripts and `attach_claude` carry `--permission-mode auto` (mirrors `tests/unit/test_session_script.py`). Integration (docker-gated, skips cleanly when docker absent): build the image and confirm a started session reports auto mode / that a denied git command is blocked.

**Target Platform**: Linux container `asdd/project:latest`, driven from a macOS operator terminal.

**Project Type**: CLI + container image (single project, conventional Python layout).

**Performance Goals**: Auto mode runs a per-action classifier, adding latency to each tool call; acceptable for interactive and batch use. No change to session startup or the held-process model.

**Constraints**: Must not open any inbound port; must not change the credential/auth model or per-project state isolation; must preserve the "one Claude process per persistent container" invariant and the `--continue`/fresh-start resume logic in `asdd-session.sh`; deny rules must hold even under auto mode; must not stall unattended modes on a first-run "approve project permission rules" prompt.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Verdict | Note |
|-----------|---------|------|
| I. Spec-Driven Development | PASS | Delivered through the full `/speckit-*` artifact set under `specs/006-*/`. |
| II. Plain Files Where Humans Read State | PASS | The guardrail is a small, human-readable JSON file in the working tree. |
| III. Single Writer per File | PASS | `.claude/settings.json` is written once by the scaffolder; no concurrent writers. |
| IV. Container-Portable Runtime | PASS | `--permission-mode auto` is a CLI flag; no host-OS facility added. The classifier's calls ride the existing Claude subscription path; the sole shared host resource remains `~/.claude/`. |
| V. Secret Hygiene | PASS | No secrets touched. |
| VI. Default Branch Protection | PASS (advances it) | The deny rules directly implement "protected from force-push, branch delete, history rewrites." |

Repo invariants (CLAUDE.md) preserved: one Claude process per persistent
container (the flag decorates the existing single launch, spawns nothing);
subscription auth default unchanged; three-deps unchanged; no spec-named paths
in the deployed install (the settings file is a project-workspace artifact, not
a deployed-install path).

**Result: PASS — no violations. Complexity Tracking not required.**

## Project Structure

### Documentation (this feature)

```text
specs/006-container-auto-permission-mode/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── permission-settings.md   # the project .claude/settings.json deny contract
│   └── container-launch.md      # the --permission-mode auto launch contract
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
docker/files/
├── asdd-session.sh          # add --permission-mode auto to both claude calls (L45, L48)
└── asdd-run-job.sh          # add --permission-mode auto to the claude --print call (L41)

asdd/
├── project_container.py     # attach_claude(): add --permission-mode auto (L448)
└── workspace.py             # scaffold(): write .claude/settings.json from skeleton

project_skeleton/
└── .claude/
    └── settings.json        # NEW — permissions.deny guardrail contract (canonical copy)

tests/unit/
├── test_session_script.py   # assert auto-mode flag in entrypoints
└── test_workspace*.py       # assert scaffold writes the settings file

USER_GUIDE.md                # document auto-mode default; remove the manual automode step
```

**Structure Decision**: Single conventional Python project (unchanged). The
change spans the container entrypoint scripts (`docker/files/`), one CLI helper
(`project_container.attach_claude`), the scaffolder (`workspace.scaffold`), a new
skeleton file, the operator guide, and unit tests. No new modules or packages.

## Key implementation notes

- **Four launch points, one flag.** `asdd-session.sh` has *two* `claude` calls
  (the `--continue` resume and the fresh-start fallback) — both need the flag, or
  resumed sessions silently drop back to prompting. `asdd-run-job.sh` uses
  `claude --print`; the flag composes with print mode. `attach_claude` runs
  `docker exec -it <c> claude`. The login path (`_login_in_container`) is
  intentionally left untouched.
- **Scaffolder is selective, not a copytree.** `workspace.scaffold` runs
  `specify init` (which itself creates a `.claude/` dir for Claude Code slash
  commands) and then copies specific files. The new step writes *only*
  `.claude/settings.json` into the existing `.claude/` dir (do not overwrite the
  directory). Source is `templates_root / ".claude" / "settings.json"`, with
  `templates_root` resolving to `${ASDD_HOME}/_templates/` (seeded from
  `project_skeleton/` by `cmd_init`) or the repo skeleton directly.
- **Deny rules hold in auto mode.** Confirmed against Claude Code docs: rule
  evaluation is deny → ask → allow, ahead of the classifier; so the guardrails
  are a deterministic floor regardless of mode.
- **First-run trust prompt.** A workspace that ships its own permission rules can
  trigger a one-time approval prompt. `asdd serve` already calls
  `auth.ensure_workspace_trusted` before starting; verify it also pre-accepts the
  permission-rules approval, and extend it if not, so unattended modes never
  stall (FR-009).
- **Backfill.** New projects are covered by the scaffolder. Existing
  `${ASDD_HOME}/projects/<id>/` workspaces get the file via a documented operator
  step in USER_GUIDE.md (copy the skeleton file in); promoting that to a
  subcommand is a deferred refinement, not required here.

See `research.md` for the decision record (auto mode vs full bypass; deny-rule
phrasing; scaffolder mechanics) and `contracts/` for the exact rule set and
launch strings.
