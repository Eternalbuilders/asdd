<!--
ASDD starter constitution.

Edit this file for your project. Every project on the ASDD platform must
have a constitution; the rules below are a permissive starting point. Use
`/speckit-constitution` inside this project to amend.

A good first amendment names:
  - what this project may do (post to GitHub, call paid APIs, etc.)
  - what this project may NOT do (no force-push to main, no shipping client
    work without review)
  - the default branch and any branch-protection invariants
-->

# Project Constitution (starter)

## Core Principles

### I. Spec-Driven Development — Non-Negotiable

Every feature MUST begin with `/speckit-specify` and produce the artifact set
`spec.md → clarifications → plan.md → research.md → data-model.md → contracts/ →
quickstart.md → tasks.md → implementation` under `specs/<NNN-feature-slug>/`.

### II. Plain Files Where Humans Read State

Operational state intended for human inspection (inboxes, jobs, results,
schedules, configs) MUST live as Markdown or YAML in this project's working
tree. Binary-only state is restricted to caches and append-only telemetry.

### III. Single Writer per File

Every file in this project's working tree has at most one writer at any
moment. The user is the writer for the inbox; agents write only new files
under `results/`; the kernel writes only its own state files.

### IV. Container-Portable Runtime

This project's agents MUST run inside containers and MUST NOT depend on
host-OS-specific facilities (Keychain, launchd, FSEvents). The sole shared
host resource is `~/.claude/` for Claude Code subscription auth.

### V. Secret Hygiene

This project's static credentials live in `_state/secrets.enc.yml` encrypted
with SOPS+age. Decrypted values MUST NOT be written to disk inside any agent
container.

### VI. Default Branch Protection

`main` is protected from destructive operations (force-push, branch delete,
history rewrites) unless this constitution is amended to opt in.

## Governance

Amendments MUST be made via pull request that edits this file. State the
version bump (PATCH / MINOR / MAJOR) and rationale in the commit message.

**Version**: 0.1.0-starter | **Ratified**: TBD | **Last Amended**: TBD
