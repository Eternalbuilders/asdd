# Quickstart: validating Container Auto Permission Mode for Git

Runnable checks that prove the feature end-to-end. See
`contracts/permission-settings.md` and `contracts/container-launch.md` for the
exact rule set and launch strings.

## Prerequisites

- Dev container (this repo) for unit tests; a Mac with Docker + a logged-in asdd
  (`asdd login`) for the end-to-end checks.
- Image rebuilt after the entrypoint-script change (`asdd` rebuilds on next
  container start, or rebuild explicitly).

## 1. Unit tests (dev container)

```bash
make test
```

Expect green, including the new assertions:
- `scaffold` writes `<workspace>/.claude/settings.json` containing the deny rules.
- `asdd-session.sh` (both claude lines) and `asdd-run-job.sh` carry
  `--permission-mode auto`; `attach_claude` adds it; `_login_in_container` does not.

## 2. New project gets guardrails with zero setup (Mac)

```bash
asdd new demo-006
cat "$ASDD_HOME/projects/demo-006/.claude/settings.json"
```

Expect the `permissions.deny` block from the contract. **SC-004** met.

## 3. Git runs without prompts, in every mode (Mac)

Interactive:

```bash
asdd claude demo-006
# in the session, ask Claude to: git status && git add -A && git commit -m "test"
```

Expect no per-command approval prompt (**SC-001**). Repeat the spirit of this for
`asdd serve demo-006` (persistent) and an `asdd dispatch` job whose markdown
instructs a commit — both should complete unattended (**SC-002**).

## 4. Destructive git is blocked, in every mode (Mac)

In any of the sessions above, have Claude attempt:

```text
git push --force
git reset --hard HEAD~1
git rebase -i HEAD~2
git commit --no-verify -m "x"
```

Each MUST be blocked rather than executed (**SC-003**), even though routine git
is auto-approved.

## 5. Backfill an existing project (Mac)

For a project created before this feature:

```bash
cp "$ASDD_HOME/_templates/.claude/settings.json" \
   "$ASDD_HOME/projects/<existing-id>/.claude/settings.json"
```

Then repeat checks 3–4 in that project. (Documented in USER_GUIDE.md.)

## 6. Confirm the mode (diagnostic)

Inside any container session, a routine auto-approved command should show the
harness note **"Allowed by auto mode classifier"** — the same signal observed in
the original frictionless container. **SC-005**: no manual per-session automode
step was needed.
