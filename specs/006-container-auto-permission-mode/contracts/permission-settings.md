# Contract: Project permission-guardrail file

**Artifact**: `<project-workspace>/.claude/settings.json`
**Canonical source**: `project_skeleton/.claude/settings.json`
**In-container path**: `/asdd_home/.claude/settings.json` (read as project settings)

## Required content

The file MUST be valid Claude Code settings JSON and MUST contain at least the
following `permissions.deny` rules. It MUST NOT set `permissions.defaultMode`
(ignored in project settings; mode is enabled via the launch flag — see
`container-launch.md`).

```json
{
  "permissions": {
    "deny": [
      "Bash(git push --force *)",
      "Bash(git push -f *)",
      "Bash(git push * --force*)",
      "Bash(git * --force*)",
      "Bash(git *force*)",
      "Bash(git reset --hard *)",
      "Bash(git rebase *)",
      "Bash(git commit * --no-verify *)",
      "Bash(git commit *-n *)"
    ]
  }
}
```

## Semantics (guaranteed by Claude Code)

- Rule evaluation order is **deny → ask → allow → auto-mode classifier**. A deny
  match blocks unconditionally, including in `auto` permission mode.
- Bash matching is literal/glob and shell-operator aware: each sub-command of a
  compound command (`a && b`, `a; b`, `a | b`) is matched independently, so
  `git status && git push --force` is blocked by the push rule.

## Guarantees

- **G1**: In any container, `git push --force` / `git push -f` and reordered
  variants are blocked.
- **G2**: `git reset --hard`, `git rebase`, and `git commit --no-verify` / `-n`
  are blocked.
- **G3**: Routine git/`gh` and other commands are NOT listed here and so are
  governed by the launch mode (auto-approved in `auto` mode).

## Known limitation

Literal matching can be evaded by env-var indirection or exotic quoting
(`U=--force; git push $U`). This file is the deterministic floor for ordinary
invocations; the written conventions in the project constitution / CLAUDE.md are
the complementary soft layer. Not in scope: OS sandbox or a semantic PreToolUse
hook.

## Coexistence

- `specify init` creates the `.claude/` directory (slash-command assets) during
  scaffolding; this file is written *into* that directory and MUST NOT overwrite
  it.
- This is the shared, committed `settings.json` — distinct from any local
  `settings.local.json` an operator may add.
