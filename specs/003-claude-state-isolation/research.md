# Research — 003-claude-state-isolation

This file resolves the open technical questions called out in `spec.md` (Assumptions, Edge Cases) and `plan.md` (Technical Context). Three decisions; each section is self-contained.

## R1. Credential-file mounting: file bind mount vs. directory remount

**Decision**: Use a single-file bind mount for `.credentials.json`, layered on top of the per-project directory mount. Same approach as `claude.json` today.

**Rationale**: The empirical question — "does Claude Code rewrite `.credentials.json` in place, or write-then-rename (which would break a file bind mount)?" — is answered by direct observation in this devcontainer, which is already running spec 009's file bind mount for `claude.json`:

```text
$ stat /home/asdd/.claude.json
  Birth: 2026-06-11 12:27:48 …    ← created days ago
  Modify: 2026-06-12 14:04:00 …   ← rewritten today, same inode
Inode: 13
```

The inode is stable across many rewrites over the past day. If Claude were doing write-temp + rename, the inode would change every rewrite (rename gives the rename target the source file's inode, displacing the original). A file bind mount survives in-place rewrites and breaks on rename. The fact that `claude.json` is being rewritten through the bind mount without operator-visible failures means Claude writes it in place. `.credentials.json` follows the same JSON-config family of files and is overwhelmingly likely to use the same write pattern; we accept this as the working assumption, and the integration test in Phase 1 / quickstart will exercise a refresh end-to-end to flush out any deviation.

**Alternatives considered**:

- **Directory mount with start-time copy + stop-time writeback.** Copy the shared `.credentials.json` into the per-project subtree at container start; sync back at container stop. Rejected: Docker has no clean "on stop" hook for the regular `start_container` path; the supervised persistent-session mode (spec 010) compounds this because stops are launchd-initiated. Adds a write-back race window without solving any problem the file mount doesn't already solve.
- **Symlink inside per-project dir pointing at the shared file.** Rejected: requires the symlink target to be mounted at a stable path inside the container that doesn't collide with `~/.claude/`. Adds a mount; symlink target dangles in the rare case Claude does atomic-rename anyway (symlink would be replaced by a real file, breaking the writeback).
- **Patch Claude Code to use an env var pointing at a custom credentials path.** Rejected: we don't control Claude Code's source; the env-var surface is not part of any stable contract we should rely on.

**Failure mode if the assumption ever breaks** (Claude switches to atomic-rename for `.credentials.json`): the next token refresh would write a new file inside the container's per-project mount layer but leave the shared host file untouched. Symptom: refresh succeeds inside that container, but other projects re-prompt for login on next start. Detectable; recoverable by `asdd login` again. We document this and move on.

## R2. Docker mount ordering: directory + file overlay

**Decision**: Pass mounts in `docker run` argv in this fixed order, with the file mount appearing _after_ the parent directory mount it overlays:

```text
-v <host>/_state/claude-auth/claude.json   :/home/asdd/.claude.json:rw       # shared, sibling of ~/.claude
-v <host>/_state/claude-auth/per-project/<project_id>/ :/home/asdd/.claude:rw  # per-project subtree
-v <host>/_state/claude-auth/claude/.credentials.json  :/home/asdd/.claude/.credentials.json:rw   # shared file, overlaid
```

The third mount targets a path _inside_ the second mount's target. Docker / the kernel processes each `-v` as an independent bind-mount syscall in argv order, and the kernel resolves mount stacks at lookup time — the deepest (most specific) mount at a path wins. Result: writes to `~/.claude/.credentials.json` inside the container go to the shared host file, while writes to anything else under `~/.claude/` go to the per-project subtree.

**Rationale**: This pattern is already used by spec 009 (mount `claude/` as a directory and overlay `claude.json` as a sibling-not-inside file). The novelty here is overlaying a file _inside_ a previously-mounted directory; Docker's mount-list processing handles this correctly because each `-v` becomes a distinct `mount(2)` and the kernel's VFS uses the most-recently-mounted entry for a given path. Verified by inspecting `/proc/self/mountinfo` inside this devcontainer (separate entries for `~/.claude.json` and `~/.claude/`).

**Alternatives considered**:

- **Mount the per-project dir at a non-`~/.claude/` path and symlink `.claude/` to it.** Rejected: Claude Code reads `~/.claude/` directly; a symlink at `~/.claude/` might or might not satisfy it depending on internal `realpath` calls. Brittle and not necessary.
- **Build a per-project tmpfs overlay (overlayfs) merging shared + per-project.** Rejected: requires extra Docker capabilities and a kernel module not guaranteed under OrbStack / lima / native Docker uniformly. Significantly more complex than three bind mounts.

## R3. Per-project directory materialisation, permissions, and migration detection

**Decision**:

- Extend `auth.ensure_mountable(asdd_home, project_id=None)` to materialise `_state/claude-auth/per-project/<project_id>/` as a `0700` directory when `project_id` is supplied. Idempotent — existing trees keep their permissions re-asserted.
- Also extend `ensure_mountable` to materialise the shared `_state/claude-auth/claude/.credentials.json` as an empty placeholder file (mode `0600`) when missing. Reuses the same `_heal_json_is_dir` self-healing pattern already used for `claude.json` — Docker auto-creates missing bind targets as directories, which would corrupt `.credentials.json` if the first container start preceded any login.
- Migration detection: legacy mixed state is identified by the presence of `_state/claude-auth/claude/projects/` (a subdirectory Claude Code only creates under per-project state — its presence in the shared store proves the pre-fix mount layout was used). A one-time notice is emitted the first time `start_container` runs after detecting that path. The notice having been shown is recorded by `touch _state/claude-auth/.migration-notice-shown`.

**Rationale**:

- Pre-materialisation is necessary because Docker auto-creates missing bind targets as directories. For a file target like `.credentials.json` this would silently corrupt the structure (next login crashes with `IsADirectoryError` — the bug the existing `_heal_json_is_dir` was added to fix for `claude.json`). The existing self-healing already handles this for `claude.json`; we apply it uniformly.
- `0700` matches the existing perms on `_state/claude-auth/claude/` and is also what `claude-auth/` itself uses (`asdd/auth.py:_ensure_store` line 115). One umask, one model.
- Marker-file migration detection beats a meta-JSON entry because (a) it's `ls`-grep-friendly for an operator inspecting state and (b) it survives `auth.clear` correctly: clearing the store removes the marker too, so a future fresh seed will not trigger the legacy notice.

**Alternatives considered**:

- **Auto-migrate the legacy mixed state into the per-project tree of "the first project started after upgrade".** Rejected — spec FR-009 explicitly prohibits this. The mixed state contains transcripts from multiple projects; assigning them all to one project is wrong.
- **Auto-delete the legacy mixed state.** Rejected — silent data loss. The operator may have unfinished work in those transcripts; they decide.
- **Never detect or notify; rely on documentation.** Rejected — the user reporting this bug (and any future upgrader) would silently keep seeing leakage from the legacy state long after the structural fix landed. The notice is the bridge.

## Open questions

None. All Technical Context entries in `plan.md` are now grounded in concrete decisions. Ready for Phase 1.
