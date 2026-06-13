# Research: Container Auto Permission Mode for Git

Phase 0 decision record. All Technical Context unknowns resolved below.

## Decision 1 — Use `auto` permission mode, not full bypass

**Decision**: Start Claude with `--permission-mode auto` in every container
launch path. Reject `--dangerously-skip-permissions`.

**Rationale**:
- The frictionless reference container was confirmed (via in-container
  diagnostic) to be running in `auto` mode — the harness printed "Allowed by
  auto mode classifier". Matching that mode reproduces the desired behaviour
  exactly.
- In `auto` mode a classifier reviews each action and auto-approves routine
  ones (git, `gh`, tests, builds) while still flagging actions that escalate
  scope or target unrecognized external infrastructure. That keeps a safety
  review in place.
- Crucially, `permissions.deny` (and `ask`) rules are still enforced in auto
  mode — evaluation order is **deny → ask → allow → classifier**. So we can keep
  hard guardrails. Full bypass (`--dangerously-skip-permissions`) ignores deny
  rules entirely, leaving no floor — rejected for that reason and to honour
  constitution VI.

**Alternatives considered**:
- *Deterministic `permissions.allow` list for `Bash(git:*)`/`Bash(gh:*)` only,
  no auto mode*: fully predictable and offline, but narrower than the reference
  container (would still prompt for tests/builds) and does not match the
  behaviour the user explicitly asked to replicate ("auto permissive in all
  ways"). Kept as a fallback if auto mode is ever unavailable.
- *`--dangerously-skip-permissions`*: rejected — no guardrails, violates VI.

## Decision 2 — `defaultMode: auto` cannot live in project settings; use the flag

**Decision**: Enable auto mode via the launch flag `--permission-mode auto`, not
via `permissions.defaultMode` in a committed file.

**Rationale**: Claude Code deliberately **ignores** `defaultMode: "auto"` in
project-level `.claude/settings.json` / `settings.local.json` (it is honoured
only in *user* settings) precisely so a repo cannot force auto mode onto a
developer. The launch flag is the supported way to start a scripted,
non-interactive session in auto mode with no human keypress. This is why the
deny-guards (which DO work in project settings) and the mode-enable (which does
not) are split across two mechanisms.

**Alternatives considered**:
- *Seed `defaultMode: auto` into the per-project user settings
  (`_state/claude-auth/per-project/<id>/settings.json`)*: would work but spreads
  the mode decision into the auth/state store and couples it to spec 003's
  isolation layout. The launch flag keeps the decision in the entrypoints where
  the other launch options already live. Rejected as more coupling for no gain.

## Decision 3 — Deny-rule phrasing for destructive git

**Decision**: Ship these `permissions.deny` rules (literal-match aware, with
reordered variants):

```
Bash(git push --force *)
Bash(git push -f *)
Bash(git push * --force*)
Bash(git * --force*)
Bash(git *force*)
Bash(git reset --hard *)
Bash(git rebase *)
Bash(git commit * --no-verify *)
Bash(git commit *-n *)
```

**Rationale**: Claude Code Bash matching is literal prefix/glob, but it *does*
parse shell operators and checks each sub-command of a compound command
independently — so `git status && git push --force` is blocked by the push rule.
The broad `Bash(git *force*)` / `Bash(git * --force*)` lines catch common
reorderings. This maps directly onto the user's git conventions (no force-push,
no history rewrite, no hook-skipping) and constitution VI.

**Known limitation (documented, not solved here)**: literal matching can be
evaded by env-var indirection (`U=--force; git push $U`) or exotic quoting. The
written agent conventions in CLAUDE.md remain the complementary soft layer; deny
rules are the deterministic floor for the ordinary case. Out of scope: an
OS-level sandbox or a PreToolUse hook that semantically parses commands.

**Alternatives considered**:
- *Per-branch protection (block force-push to `main` only)*: more permissive but
  more complex and branch-state dependent; branch-agnostic blocking is simpler
  and strictly satisfies VI. Rejected.

## Decision 4 — Scaffolder wiring (selective, not copytree)

**Decision**: Add a step to `asdd/workspace.py:scaffold` that copies
`templates_root / ".claude" / "settings.json"` to `<workspace>/.claude/
settings.json`, creating the dir if needed and writing only that file.

**Rationale**: `scaffold` is selective — it runs `specify init` (which itself
creates a `.claude/` directory for Claude Code slash-command assets) and then
copies specific files (e.g. `constitution-starter.md` → constitution). A blind
copytree is not used and would clobber `specify init`'s `.claude/`. Writing just
the single `settings.json` into the (already-present) `.claude/` dir is safe and
idempotent, mirroring the existing `shutil.copy2` constitution step. The canonical
source is `project_skeleton/.claude/settings.json`; `cmd_init` already
`copytree`s `project_skeleton/` → `${ASDD_HOME}/_templates/`, and `copytree`
includes dotfiles, so the file reaches `_templates` for free.

**Alternatives considered**:
- *Generate the JSON inline in Python*: avoids a skeleton file but hides the
  contract from operators and duplicates the rule list in code. Rejected — a
  checked-in file is more inspectable (constitution II) and is itself the
  contract artifact.

## Decision 5 — Backfill existing projects via documented step

**Decision**: Document a one-line operator step in USER_GUIDE.md to drop the
skeleton `.claude/settings.json` into pre-existing `${ASDD_HOME}/projects/<id>/`
workspaces. Do not build a subcommand in this feature.

**Rationale**: The scaffolder covers all new projects (the common path). Existing
projects are few and operator-owned; a documented copy step is sufficient and
keeps the command surface unchanged. A dedicated `asdd` subcommand is a possible
later refinement, recorded as deferred.

## Decision 6 — First-run permission-rules trust prompt (no code needed)

**Decision**: Ship the guardrails as **deny-only** rules and rely on the existing
`auth.ensure_workspace_trusted` (workspace-trust pre-accept). No new `auth.py`
code is required for FR-009.

**Rationale**: Verified against Claude Code behaviour/docs: a project
`.claude/settings.json` that contains **only** `permissions.deny` rules triggers
**no** additional first-run approval prompt — deny rules only restrict, never
grant, so they apply immediately. The sole first-run gate is the workspace-trust
dialog, which `ensure_workspace_trusted` already pre-accepts via
`hasTrustDialogAccepted` in the mounted `claude.json`. There is currently no
pre-accept key for permission rules themselves (tracked upstream), but deny-only
rules never reach that path. Had we shipped `allow`/`ask` rules, a prompt could
appear; keeping the file deny-only sidesteps it entirely and is also the safer
design (auto mode + classifier handles the "allow" side).

**Consequence**: T008 reduces to a verification + a regression test that the
skeleton stays deny-only (`test_skeleton_permissions.py::
test_skeleton_settings_has_no_project_level_default_mode` and the deny-set test);
no change to `auth.py`.
