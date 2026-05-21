"""ASDD bootstrap & management CLI (T030-T034 / US1; spec 008 T112-T115).

Single entry point for project lifecycle ops. Exposed as the ``asdd``
console script via ``pyproject.toml`` and importable from inside the
kernel container for inbox-driven invocation.

Subcommands:
  asdd init                            — initialise ${ASDD_HOME}
  asdd new <id> [--from-remote URL]    — create a new project
  asdd list [--include-archived]       — show registered projects
  asdd open <id>                       — open a project's container (spec 008)
  asdd close <id>                      — stop a project's container (spec 008)
  asdd ps                              — list running project containers (spec 008)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
import yaml

from asdd import auth, lifecycle, project_container, secrets, supervisor, workspace
from asdd._schemas import validate_registry
from asdd.registry import Project

log = logging.getLogger("asdd.bootstrap")


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATES = REPO_ROOT / "project_skeleton"
BOOTSTRAP_BRANCH = "asdd/bootstrap"


class BootstrapError(RuntimeError):
    """User-facing bootstrap failure with a clear message."""


# ---------------------------------------------------------------------------
# Registry I/O helpers (operator is the writer per Principle VI)
# ---------------------------------------------------------------------------


def _registry_path(asdd_home: Path) -> Path:
    return asdd_home / "_state" / "projects.yml"


def _iso_utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_registry_raw(asdd_home: Path) -> dict[str, Any]:
    path = _registry_path(asdd_home)
    if not path.exists():
        raise BootstrapError(f"{path} does not exist; run `asdd init` first")
    return yaml.safe_load(path.read_text())


def _write_registry_atomic(asdd_home: Path, data: dict[str, Any]) -> None:
    """Validate against the schema then atomically replace projects.yml."""
    validate_registry(data)
    path = _registry_path(asdd_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    # write-temp-then-rename for atomicity
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".projects.", suffix=".yml.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_init(*, asdd_home: Path, templates_src: Path | None = None) -> None:
    """Initialise ${ASDD_HOME}: create _state/, templates, empty registry.

    Idempotent — calling on an already-initialised home is a no-op.
    """
    templates_src = templates_src or DEFAULT_TEMPLATES
    if not templates_src.is_dir():
        raise BootstrapError(
            f"templates directory not found at {templates_src}; "
            f"the repo's project_skeleton/ must exist"
        )

    (asdd_home / "_state").mkdir(parents=True, exist_ok=True)
    (asdd_home / "projects").mkdir(parents=True, exist_ok=True)
    (asdd_home / "_archive").mkdir(parents=True, exist_ok=True)

    # Copy templates root into the home if missing.
    home_templates = asdd_home / "_templates"
    if not home_templates.exists():
        shutil.copytree(templates_src, home_templates)
        log.info("[init] copied templates to %s", home_templates)

    # Initial registry — only if missing
    reg_path = _registry_path(asdd_home)
    if not reg_path.exists():
        initial = {
            "version": 1,
            "default_project_id": "vaultcontrol",
            "projects": [],
        }
        _write_registry_atomic(asdd_home, initial)
        log.info("[init] created registry at %s", reg_path)

    # audit.log exists
    (asdd_home / "_state" / "audit.log").touch(exist_ok=True)


def _git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
    """Run a git command in ``cwd``; raise BootstrapError on non-zero exit."""
    try:
        return subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
    except subprocess.CalledProcessError as e:
        raise BootstrapError(
            f"git {' '.join(args)} failed: {e.stderr.strip() or e.stdout.strip()}"
        ) from e


def _emit_progress(step: str, **fields: Any) -> None:
    """Structured progress signal to stderr (FR-010)."""
    payload = {"step": step, **fields}
    print(f"[asdd] {json.dumps(payload, separators=(',', ':'))}", file=sys.stderr)


def cmd_new(
    *,
    asdd_home: Path,
    project_id: str,
    from_remote: str | None = None,
    description: str | None = None,
    name: str | None = None,
    templates_src: Path | None = None,
) -> dict[str, Any]:
    """Bootstrap a new project. See spec.md US1 for the full scenario set."""
    templates_src = templates_src or (
        asdd_home / "_templates" if (asdd_home / "_templates").is_dir() else DEFAULT_TEMPLATES
    )

    # 1. Refuse duplicate id (US1.2)
    raw = _read_registry_raw(asdd_home)
    existing_ids = {p["id"] for p in raw.get("projects", [])}
    if project_id in existing_ids:
        raise BootstrapError(f"project {project_id!r} already registered")

    workspace_path = asdd_home / "projects" / project_id
    if workspace_path.exists():
        raise BootstrapError(
            f"workspace path {workspace_path} already exists; refusing to overwrite"
        )

    _emit_progress("start", project_id=project_id)

    # Capture the pre-bootstrap registry so rollback restores byte-for-byte.
    reg_path = _registry_path(asdd_home)
    pre_bootstrap_bytes = reg_path.read_bytes()

    try:
        # 2. Get the working tree on disk
        if from_remote:
            _emit_progress("clone", remote=from_remote)
            _git(
                ["clone", "--quiet", from_remote, str(workspace_path)],
                cwd=asdd_home,
            )
            # Set local committer for any commits we make
            _git(["config", "user.email", "asdd-bootstrap@local"], cwd=workspace_path)
            _git(["config", "user.name", "asdd bootstrap"], cwd=workspace_path)
            # US1.3 — spec additions go on a NEW branch, not main
            _git(["checkout", "-b", BOOTSTRAP_BRANCH], cwd=workspace_path)
        else:
            _emit_progress("init_workspace", path=str(workspace_path))
            workspace_path.mkdir(parents=True)
            _git(["init", "--initial-branch=main", "--quiet"], cwd=workspace_path)
            _git(["config", "user.email", "asdd-bootstrap@local"], cwd=workspace_path)
            _git(["config", "user.name", "asdd bootstrap"], cwd=workspace_path)

        # 3. Lay down .specify/, constitution, queue dirs
        _emit_progress("scaffold")
        workspace.scaffold(workspace_path, templates_root=templates_src)

        # 4. Commit the scaffolding
        _emit_progress("commit_scaffold")
        _git(["add", "."], cwd=workspace_path)
        _git(
            ["commit", "--quiet", "-m", f"asdd: scaffold project {project_id}"],
            cwd=workspace_path,
        )

        # 5. Append registry row (atomic write of the whole file)
        _emit_progress("register")
        now = _iso_utc_now()
        new_row = {
            "id": project_id,
            "name": name or project_id,
            "workspace_path": str(workspace_path),
            "git_remote": from_remote,
            "default_branch": "main",
            "lifecycle_state": "active",
            "created_at": now,
            "last_checked_at": now,
            "description": description,
        }
        updated = dict(raw)
        updated["projects"] = [*raw.get("projects", []), new_row]
        _write_registry_atomic(asdd_home, updated)

        _emit_progress("done", project_id=project_id, workspace=str(workspace_path))
        return new_row

    except Exception as e:
        # Rollback — remove the partial workspace and restore the registry.
        _emit_progress("rollback", reason=str(e))
        try:
            if workspace_path.exists():
                shutil.rmtree(workspace_path)
        except OSError:
            log.exception("rollback: failed to remove %s", workspace_path)
        try:
            reg_path.write_bytes(pre_bootstrap_bytes)
        except OSError:
            log.exception("rollback: failed to restore registry")
        if isinstance(e, BootstrapError):
            raise
        raise BootstrapError(f"bootstrap failed: {e}") from e


def cmd_list(
    *,
    asdd_home: Path,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Return the registered projects as a list of dicts (US1 supporting cmd)."""
    raw = _read_registry_raw(asdd_home)
    rows = list(raw.get("projects", []))
    if not include_archived:
        rows = [r for r in rows if r["lifecycle_state"] != "archived"]
    return rows


# ---------------------------------------------------------------------------
# US5 — lifecycle transitions
# ---------------------------------------------------------------------------


def _transition(asdd_home: Path, project_id: str, new_state: str) -> dict[str, Any]:
    """Validate + apply a lifecycle transition for one project.

    Atomic registry write. Refuses if the project does not exist, or if the
    transition is not allowed per asdd.lifecycle.can_transition.
    """
    raw = _read_registry_raw(asdd_home)
    rows = list(raw.get("projects", []))
    target = next((r for r in rows if r["id"] == project_id), None)
    if target is None:
        raise BootstrapError(f"project {project_id!r} not found in registry")

    current = target["lifecycle_state"]
    if not lifecycle.can_transition(current, new_state):  # type: ignore[arg-type]
        raise BootstrapError(
            f"cannot transition project {project_id!r} from {current!r} to {new_state!r}"
        )
    target["lifecycle_state"] = new_state
    target["last_checked_at"] = _iso_utc_now()
    updated = dict(raw)
    updated["projects"] = rows
    _write_registry_atomic(asdd_home, updated)
    _emit_progress("lifecycle", project_id=project_id, from_=current, to=new_state)
    return target


def cmd_pause(*, asdd_home: Path, project_id: str) -> dict[str, Any]:
    """Pause a project. New work for it is held until resume."""
    return _transition(asdd_home, project_id, "paused")


def cmd_resume(*, asdd_home: Path, project_id: str) -> dict[str, Any]:
    """Resume a paused project."""
    return _transition(asdd_home, project_id, "active")


def cmd_archive(*, asdd_home: Path, project_id: str) -> dict[str, Any]:
    """Archive a project. Snapshots the workspace into _archive/ then marks terminal.

    The on-disk workspace is left in place so the operator can manually delete
    after verifying the tarball. New dispatches for this project are refused
    at the kernel level via lifecycle state.
    """
    raw = _read_registry_raw(asdd_home)
    target = next((r for r in raw.get("projects", []) if r["id"] == project_id), None)
    if target is None:
        raise BootstrapError(f"project {project_id!r} not found in registry")
    workspace_path = Path(target["workspace_path"])

    # FR-014 (spec 010): tear down any persistent session + its supervisor so
    # archiving doesn't leave an orphaned agent trying to start a dead project.
    try:
        supervisor.uninstall(project_id)
    except supervisor.SupervisorError:
        log.warning("archive: could not remove supervisor for %s", project_id)
    project_container.stop_container(project_id)
    project_container.remove_container(project_id, force=True)

    # Snapshot to _archive/<id>-<ts>.tar.gz before the state transition.
    archive_dir = asdd_home / "_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = _iso_utc_now().replace(":", "").replace("-", "")
    tar_path = archive_dir / f"{project_id}-{ts}.tar.gz"
    if workspace_path.exists():
        import tarfile

        with tarfile.open(tar_path, "w:gz") as tf:
            tf.add(workspace_path, arcname=project_id)
        _emit_progress("archive_snapshot", project_id=project_id, tar=str(tar_path))

    return _transition(asdd_home, project_id, "archived")


# ---------------------------------------------------------------------------
# Spec 008 — per-project containers
# ---------------------------------------------------------------------------


def _registry_lookup(asdd_home: Path, project_id: str) -> dict[str, Any]:
    """Look up a project row; raise BootstrapError with a clear message if absent
    or in a state that refuses container ops (FR-011)."""
    raw = _read_registry_raw(asdd_home)
    target = next(
        (r for r in raw.get("projects", []) if r["id"] == project_id), None
    )
    if target is None:
        known = ", ".join(r["id"] for r in raw.get("projects", []))
        raise BootstrapError(
            f"project {project_id!r} is not registered "
            f"(known: {known or '(none)'})"
        )
    state = target["lifecycle_state"]
    if state == "archived":
        raise BootstrapError(
            f"project {project_id!r} is archived; "
            f"restore it before opening a container"
        )
    workspace_path = Path(target["workspace_path"])
    if not workspace_path.is_dir():
        raise BootstrapError(
            f"project {project_id!r} workspace not found at "
            f"{workspace_path} (registry may be stale; reconcile first)"
        )
    return target


def _registry_row_as_project(row: dict[str, Any]) -> Project:
    """Convert a raw registry row to the ``Project`` dataclass `secrets.decrypt_project` expects."""
    return Project(
        id=row["id"],
        name=row.get("name", row["id"]),
        workspace_path=row["workspace_path"],
        git_remote=row.get("git_remote"),
        default_branch=row.get("default_branch", "main"),
        lifecycle_state=row["lifecycle_state"],
        created_at=row.get("created_at", ""),
        last_checked_at=row.get("last_checked_at", ""),
        description=row.get("description"),
    )


def _decrypt_project_secrets(row: dict[str, Any]) -> dict[str, str]:
    """Decrypt the project's secrets; return empty dict if none configured.

    Wraps `secrets.decrypt_project`. Operators without a project secrets
    file see an empty mapping (not an error) — secrets are opt-in.
    """
    proj = _registry_row_as_project(row)
    secrets_file = proj.workspace / "_state" / "secrets.enc.yml"
    if not secrets_file.exists():
        return {}
    return secrets.decrypt_project(proj)


def cmd_open(*, asdd_home: Path, project_id: str) -> int:
    """Open a project's container interactively (spec 008 FR-001).

    Returns the bash exit code from inside the container.
    Always stops the container on exit (FR-004); a stale container can
    be cleaned up by `asdd close`.
    """
    row = _registry_lookup(asdd_home, project_id)

    # FR-013: if a persistent session is already running, attach to it rather
    # than starting a second container.
    if project_container.is_persistent_running(project_id):
        return project_container.attach_session(project_id)

    _require_login(asdd_home, interactive=True)

    project_container.ensure_image_built()
    project_container.assert_not_running(project_id)

    project_secrets = _decrypt_project_secrets(row)

    pc_obj = project_container.ProjectContainer(
        project_id=project_id,
        mode="interactive",
        workspace_path=Path(row["workspace_path"]),
        asdd_home=asdd_home,
    )
    project_container.start_container(pc_obj, extra_env=project_secrets)
    try:
        return project_container.attach_shell(project_id)
    finally:
        project_container.stop_container(project_id)


def cmd_close(*, asdd_home: Path, project_id: str) -> bool:
    """Stop a project's container (manual escape hatch for abnormal exits).

    Returns True if a container was running and was stopped; False if
    nothing was running.
    """
    # Validate the project exists; otherwise the operator may have made a typo
    # and we'd silently exit successfully.
    _registry_lookup(asdd_home, project_id)
    return project_container.stop_container(project_id)


def cmd_ps() -> list[dict[str, str]]:
    """List running project containers (spec 008 supporting cmd)."""
    return project_container.list_running()


def cmd_dispatch(
    *, asdd_home: Path, project_id: str, job_path: Path, use_api_key: bool = False
) -> Path:
    """Run one autonomous-mode job inside a project's container (spec 008 US5 / FR-009).

    By default the job authenticates on the operator's subscription via the
    mounted credential store (spec 009 FR-002); pass ``use_api_key`` to bill
    the run to ``ANTHROPIC_API_KEY`` instead and suppress the store mount
    (FR-007). Invokes the in-image `asdd-run-job` shim against the job-note
    file, captures the result to the project's `results/` dir, and stops the
    container.

    The ``job_path`` MUST resolve to a path under the project's
    workspace (so the in-container path is reachable through the
    workspace bind mount). Returns the host-side path to the result file.

    Raises BootstrapError on validation failures; ProjectContainerError
    on container/runner failures.
    """
    row = _registry_lookup(asdd_home, project_id)
    workspace_path = Path(row["workspace_path"]).resolve()

    job_path = Path(job_path).resolve()
    if not job_path.is_file():
        raise BootstrapError(f"job-note not found at {job_path}")
    try:
        job_rel = job_path.relative_to(workspace_path)
    except ValueError as e:
        raise BootstrapError(
            f"job-note {job_path} is not under project workspace "
            f"{workspace_path}; place it under the workspace so the "
            f"bind mount makes it visible to the container"
        ) from e

    # Subscription is the default; fail fast (no prompt) if not logged in,
    # unless the operator opted into API-key billing for this run.
    in_container_path = f"{project_container.IN_CONTAINER_WORKDIR}/{job_rel}"

    # FR-013: if a persistent session is already up for this project, run the
    # job inside that warm container (no second container, no start/stop).
    if project_container.is_persistent_running(project_id):
        _run_job_exec(project_id, in_container_path, job_rel)
    else:
        if not use_api_key:
            _require_login(asdd_home, interactive=False)
        project_container.ensure_image_built()
        project_container.assert_not_running(project_id)
        project_secrets = _decrypt_project_secrets(row)
        pc_obj = project_container.ProjectContainer(
            project_id=project_id,
            mode="autonomous",
            workspace_path=workspace_path,
            asdd_home=asdd_home,
            use_api_key=use_api_key,
        )
        project_container.start_container(pc_obj, extra_env=project_secrets)
        try:
            _run_job_exec(project_id, in_container_path, job_rel)
        finally:
            project_container.stop_container(project_id)

    result_file = workspace_path / "results" / f"{job_path.stem}.result.md"
    return result_file


def _run_job_exec(project_id: str, in_container_path: str, job_rel: Path) -> None:
    """Run the in-image job shim inside an already-running container."""
    result = subprocess.run(
        [
            "docker",
            "exec",
            project_container.container_name(project_id),
            "asdd-run-job",
            in_container_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise project_container.ProjectContainerError(
            f"{_classify_job_failure(detail)} "
            f"(asdd-run-job exited {result.returncode} for {job_rel}: {detail})"
        )


# ---------------------------------------------------------------------------
# Spec 007 US6 — per-project secrets CLI
# ---------------------------------------------------------------------------


def cmd_secrets_add(
    *,
    asdd_home: Path,
    project_id: str,
    key: str,
    value: str,
    recipient: str | None = None,
) -> None:
    """Add or update one secret in the project's encrypted store (T059).

    Refuses if the project is archived (no new secrets added to dead projects).
    First-time call requires an age recipient via ``recipient`` arg or
    ``SOPS_AGE_RECIPIENTS`` env var.
    """
    row = _registry_lookup(asdd_home, project_id)
    try:
        secrets.add_secret(
            Path(row["workspace_path"]),
            key,
            value,
            recipient=recipient,
        )
    except (secrets.SecretsConfigError, secrets.SopsEncryptError) as e:
        raise BootstrapError(str(e)) from e


def cmd_secrets_remove(
    *,
    asdd_home: Path,
    project_id: str,
    key: str,
) -> bool:
    """Remove one secret from the project's encrypted store (T060).

    Returns True iff a key was actually removed. Returns False (no error)
    if the key wasn't present — operators get a clear stdout message.
    """
    row = _registry_lookup(asdd_home, project_id)
    try:
        return secrets.remove_secret(Path(row["workspace_path"]), key)
    except secrets.SopsEncryptError as e:
        raise BootstrapError(str(e)) from e


def cmd_secrets_list(*, asdd_home: Path, project_id: str) -> list[str]:
    """List the secret keys for a project — values are not revealed (T060)."""
    row = _registry_lookup(asdd_home, project_id)
    return secrets.list_keys(Path(row["workspace_path"]))


# ---------------------------------------------------------------------------
# Spec 009 — subscription credential store
# ---------------------------------------------------------------------------


def cmd_login(*, asdd_home: Path, fresh: bool = False) -> str:
    """Establish the asdd-owned subscription credential store (spec 009 US1).

    Seeds from the operator's existing host login when present and ``fresh``
    is False; otherwise runs a fresh interactive ``claude`` login inside a
    container with the store mounted. Returns the source
    (``seeded-from-host`` | ``fresh-login``). Raises BootstrapError on
    failure.
    """
    if not fresh and auth.host_login_present():
        with auth.store_lock(asdd_home):
            try:
                auth.seed_from_host(asdd_home)
            except auth.AuthError as e:
                raise BootstrapError(str(e)) from e
            # A host login can carry config but no portable credential file
            # to copy. Guard against seeding a store that wouldn't actually
            # authenticate, and direct the operator to log in in-container.
            if not auth.has_credential(asdd_home):
                auth.clear(asdd_home)
                raise BootstrapError(
                    "host Claude config was found but no portable credential "
                    "file (~/.claude/.credentials.json) to copy. Run "
                    "`asdd login --fresh` to log in inside a container."
                )
        _emit_progress("login", source=auth.SOURCE_SEEDED)
        return auth.SOURCE_SEEDED

    # Fresh / no host login: interactive in-container login.
    project_container.ensure_image_built()
    with auth.store_lock(asdd_home):
        auth.prepare_empty_store(asdd_home)
    rc = project_container.run_interactive_login(asdd_home)
    if rc != 0 or not auth.has_credential(asdd_home):
        with auth.store_lock(asdd_home):
            auth.clear(asdd_home)
        raise BootstrapError(
            "in-container `claude` login did not produce a credential "
            f"(exit {rc}); nothing stored. Re-run `asdd login --fresh` and "
            "complete the login prompt."
        )
    auth.mark_fresh_login(asdd_home)
    _emit_progress("login", source=auth.SOURCE_FRESH)
    return auth.SOURCE_FRESH


def cmd_logout(*, asdd_home: Path) -> bool:
    """Clear the subscription credential store (spec 009 FR-011). Idempotent."""
    with auth.store_lock(asdd_home):
        removed = auth.clear(asdd_home)
    _emit_progress("logout", removed=removed)
    return removed


def cmd_whoami(*, asdd_home: Path) -> auth.AuthStatus:
    """Return local auth status without any network call (spec 009 FR-011)."""
    return auth.status(asdd_home)


def _classify_job_failure(detail: str) -> str:
    """Map a Claude/runner failure to the FR-013 operator-facing category."""
    low = detail.lower()
    auth_signals = ("401", "unauthorized", "authentication", "invalid api key", "oauth", "log in", "login")
    limit_signals = ("rate limit", "usage limit", "quota", "429", "limit reached")
    if any(s in low for s in limit_signals):
        return "subscription usage limit reached — wait for the window to reset or upgrade"
    if any(s in low for s in auth_signals):
        return "re-login required — run `asdd login`"
    return "job failed"


def _require_login(asdd_home: Path, *, interactive: bool) -> None:
    """Guard for credentialed runs. Autonomous callers must fail fast; the
    interactive caller gets the same error but the CLI layer turns it into
    guidance (spec 009 FR-006)."""
    if not auth.is_logged_in(asdd_home):
        raise BootstrapError(
            "no subscription login found — run `asdd login` first "
            "(or pass --api-key to use ANTHROPIC_API_KEY for this run)"
        )


# ---------------------------------------------------------------------------
# Spec 010 — persistent supervised sessions
# ---------------------------------------------------------------------------


def _restarts_file(asdd_home: Path, project_id: str) -> Path:
    return asdd_home / "_state" / "sessions" / f"{project_id}.restarts"


def _read_restarts(asdd_home: Path, project_id: str) -> int:
    p = _restarts_file(asdd_home, project_id)
    try:
        return int(p.read_text().strip())
    except (OSError, ValueError):
        return 0


def _write_restarts(asdd_home: Path, project_id: str, n: int) -> None:
    p = _restarts_file(asdd_home, project_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{n}\n")


def _start_persistent_container(asdd_home: Path, project_id: str) -> None:
    """Run a fresh persistent container for the project (image must exist)."""
    row = _registry_lookup(asdd_home, project_id)
    pc_obj = project_container.ProjectContainer(
        project_id=project_id,
        mode="persistent",
        workspace_path=Path(row["workspace_path"]),
        asdd_home=asdd_home,
    )
    project_container.start_container(pc_obj, extra_env=_decrypt_project_secrets(row))


def cmd_serve(*, asdd_home: Path, project_id: str) -> bool:
    """Start a project's persistent session and install its supervisor (US1).

    Brings the container up now, then installs the launchd babysitter agent
    (KeepAlive) that keeps it alive thereafter. Idempotent: returns False
    (no-op) if a persistent session is already running; True if it started
    one. Fails fast if not logged in (FR-003) or if a non-persistent
    container is already running for the project.
    """
    row = _registry_lookup(asdd_home, project_id)  # refuses archived
    if project_container.is_persistent_running(project_id):
        _emit_progress("serve", project_id=project_id, state="already-running")
        return False

    _require_login(asdd_home, interactive=False)
    project_container.ensure_image_built()
    project_container.assert_not_running(project_id)
    # Clear any stale stopped container of the same name (persistent
    # containers run without --rm, so one can linger after a crash/stop).
    project_container.remove_container(project_id)
    # Pre-accept the workspace-trust dialog so the unattended (launchd-started)
    # interactive `claude --remote-control` doesn't block on it (spec 010).
    auth.ensure_workspace_trusted(asdd_home, project_container.IN_CONTAINER_WORKDIR)

    project_secrets = _decrypt_project_secrets(row)
    pc_obj = project_container.ProjectContainer(
        project_id=project_id,
        mode="persistent",
        workspace_path=Path(row["workspace_path"]),
        asdd_home=asdd_home,
    )
    project_container.start_container(pc_obj, extra_env=project_secrets)
    _write_restarts(asdd_home, project_id, 0)
    try:
        # Pin ASDD_HOME and PATH so the launchd babysitter (minimal env) can
        # find docker, asdd, and any pipx/brew shims on the operator's PATH.
        env_pins: dict[str, str] = {"ASDD_HOME": str(asdd_home)}
        if path := os.environ.get("PATH"):
            env_pins["PATH"] = path
        supervisor.install(project_id, environ=env_pins)
    except supervisor.SupervisorError as e:
        raise BootstrapError(str(e)) from e
    _emit_progress("serve", project_id=project_id, state="started")
    return True


def cmd_serve_supervise(*, asdd_home: Path, project_id: str) -> int:
    """Foreground babysitter run by the launchd agent (spec 010).

    Ensures the session container is up — counting a (re)start when it has to
    bring it back — then blocks until the container exits. On return, launchd
    (KeepAlive) relaunches this, which is what restarts a crashed session.
    """
    try:
        if not project_container.is_running(project_id):
            if project_container.exists(project_id):
                project_container.start_existing(project_id)
            else:
                project_container.ensure_image_built()
                _start_persistent_container(asdd_home, project_id)
            _write_restarts(asdd_home, project_id, _read_restarts(asdd_home, project_id) + 1)
            _emit_progress("supervise_restart", project_id=project_id)
        return project_container.wait_container(project_id)
    except (OSError, project_container.ProjectContainerError) as e:
        # Log so launchd's stderr capture shows what failed, then exit non-zero
        # so it's visible in `launchctl print`; KeepAlive relaunches regardless.
        log.error("babysitter error for %r: %s", project_id, e)
        return 1


def cmd_attach(*, asdd_home: Path, project_id: str) -> int:
    """Attach to a project's running persistent session (US3).

    Returns claude's exit code. Refuses (does not start one) if no session is
    running.
    """
    _registry_lookup(asdd_home, project_id)
    if not project_container.is_persistent_running(project_id):
        raise BootstrapError(
            f"no persistent session running for {project_id!r}; "
            f"start one with `asdd serve {project_id}`"
        )
    return project_container.attach_session(project_id)


def cmd_stop(*, asdd_home: Path, project_id: str) -> bool:
    """Authoritatively stop a persistent session (US4).

    Disables the supervisor *first* (so it cannot relaunch), then stops and
    removes the container so the restart policy cannot bring it back.
    Idempotent; returns True iff something was running.
    """
    _registry_lookup(asdd_home, project_id)
    try:
        supervisor.uninstall(project_id)
    except supervisor.SupervisorError as e:
        raise BootstrapError(str(e)) from e
    stopped = project_container.stop_container(project_id)
    project_container.remove_container(project_id, force=True)
    _emit_progress("stop", project_id=project_id, stopped=stopped)
    return stopped


def cmd_session_status(*, asdd_home: Path, project_id: str) -> dict[str, Any]:
    """Derived session status — no network call (US2 / FR-011)."""
    _registry_lookup(asdd_home, project_id)
    return {
        "project_id": project_id,
        "running": project_container.is_running(project_id),
        "mode": project_container.running_mode(project_id),
        # Restarts are counted by the babysitter (Docker's RestartCount is
        # unusable here — the babysitter, not the restart policy, restarts it).
        "restart_count": _read_restarts(asdd_home, project_id),
        "state": project_container.state(project_id),
        "supervised": supervisor.is_installed(project_id),
    }


# ---------------------------------------------------------------------------
# Click CLI surface
# ---------------------------------------------------------------------------


def _asdd_home_from_env() -> Path:
    h = os.environ.get("ASDD_HOME")
    if h:
        return Path(h)
    return Path.home() / "Code" / "asdd"


@click.group(help="ASDD platform management CLI.")
@click.version_option(package_name="asdd")
def cli() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


@cli.command("init", help="Initialise ${ASDD_HOME} (idempotent).")
def _cli_init() -> None:
    home = _asdd_home_from_env()
    cmd_init(asdd_home=home)
    click.echo(f"ASDD home initialised at {home}")


@cli.command("new", help="Bootstrap a new ASDD project.")
@click.argument("project_id")
@click.option("--from-remote", default=None, help="Git remote URL to clone.")
@click.option("--description", default=None, help="One-line project description.")
@click.option("--name", default=None, help="Human-readable name (defaults to id).")
def _cli_new(
    project_id: str, from_remote: str | None, description: str | None, name: str | None
) -> None:
    home = _asdd_home_from_env()
    try:
        row = cmd_new(
            asdd_home=home,
            project_id=project_id,
            from_remote=from_remote,
            description=description,
            name=name,
        )
    except BootstrapError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    click.echo(f"Project {row['id']!r} bootstrapped at {row['workspace_path']}")


@cli.command("list", help="Show registered projects.")
@click.option("--include-archived/--no-include-archived", default=False)
@click.option("--format", "fmt", type=click.Choice(["table", "json", "yaml"]), default="table")
def _cli_list(include_archived: bool, fmt: str) -> None:
    home = _asdd_home_from_env()
    try:
        rows = cmd_list(asdd_home=home, include_archived=include_archived)
    except BootstrapError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    if fmt == "json":
        click.echo(json.dumps(rows, indent=2))
    elif fmt == "yaml":
        click.echo(yaml.safe_dump(rows, sort_keys=False, default_flow_style=False))
    else:
        # table
        if not rows:
            click.echo("(no projects)")
            return
        click.echo(f"{'ID':24} {'STATE':12} {'NAME':24}")
        for r in rows:
            click.echo(f"{r['id']:24} {r['lifecycle_state']:12} {r.get('name', ''):24}")


@cli.command("pause", help="Pause a project (holds new work until resume).")
@click.argument("project_id")
def _cli_pause(project_id: str) -> None:
    home = _asdd_home_from_env()
    try:
        cmd_pause(asdd_home=home, project_id=project_id)
    except BootstrapError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    click.echo(f"Project {project_id!r} paused")


@cli.command("resume", help="Resume a paused project.")
@click.argument("project_id")
def _cli_resume(project_id: str) -> None:
    home = _asdd_home_from_env()
    try:
        cmd_resume(asdd_home=home, project_id=project_id)
    except BootstrapError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    click.echo(f"Project {project_id!r} resumed")


@cli.command("archive", help="Archive a project (snapshot + terminal state).")
@click.argument("project_id")
def _cli_archive(project_id: str) -> None:
    home = _asdd_home_from_env()
    try:
        cmd_archive(asdd_home=home, project_id=project_id)
    except BootstrapError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    click.echo(f"Project {project_id!r} archived")


@cli.command("open", help="Open a project's container (interactive bash inside).")
@click.argument("project_id")
def _cli_open(project_id: str) -> None:
    home = _asdd_home_from_env()
    try:
        rc = cmd_open(asdd_home=home, project_id=project_id)
    except BootstrapError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    except project_container.AlreadyRunningError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    except project_container.ProjectContainerError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    sys.exit(rc)


@cli.command("close", help="Stop a project's container (manual escape hatch).")
@click.argument("project_id")
def _cli_close(project_id: str) -> None:
    home = _asdd_home_from_env()
    try:
        stopped = cmd_close(asdd_home=home, project_id=project_id)
    except BootstrapError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    except project_container.ProjectContainerError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    if stopped:
        click.echo(f"Project {project_id!r} stopped")
    else:
        click.echo(f"Project {project_id!r} was not running")


@cli.command("serve", help="Start a project's persistent supervised session.")
@click.argument("project_id")
@click.option(
    "--supervise",
    is_flag=True,
    hidden=True,
    default=False,
    help="Internal: run the foreground launchd babysitter (do not call directly).",
)
def _cli_serve(project_id: str, supervise: bool) -> None:
    home = _asdd_home_from_env()
    if supervise:
        # Foreground babysitter invoked by the launchd agent. Block until the
        # container exits, then exit so launchd (KeepAlive) relaunches us.
        cmd_serve_supervise(asdd_home=home, project_id=project_id)
        sys.exit(0)
    try:
        started = cmd_serve(asdd_home=home, project_id=project_id)
    except (BootstrapError, project_container.ProjectContainerError, supervisor.SupervisorError) as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    except project_container.AlreadyRunningError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    click.echo(
        f"session for {project_id!r} started"
        if started
        else f"session for {project_id!r} already running"
    )


@cli.command("attach", help="Attach to a project's running persistent session.")
@click.argument("project_id")
def _cli_attach(project_id: str) -> None:
    home = _asdd_home_from_env()
    try:
        rc = cmd_attach(asdd_home=home, project_id=project_id)
    except (BootstrapError, project_container.ProjectContainerError) as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    sys.exit(rc)


@cli.command("stop", help="Stop a persistent session and disable its supervisor.")
@click.argument("project_id")
def _cli_stop(project_id: str) -> None:
    home = _asdd_home_from_env()
    try:
        stopped = cmd_stop(asdd_home=home, project_id=project_id)
    except (BootstrapError, project_container.ProjectContainerError, supervisor.SupervisorError) as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    click.echo(
        f"session for {project_id!r} stopped"
        if stopped
        else f"session for {project_id!r} was not running (supervisor cleared)"
    )


@cli.group("session", help="Inspect persistent sessions.")
def _cli_session() -> None:
    pass


@_cli_session.command("status", help="Show a project's persistent-session status.")
@click.argument("project_id")
def _cli_session_status(project_id: str) -> None:
    home = _asdd_home_from_env()
    try:
        st = cmd_session_status(asdd_home=home, project_id=project_id)
    except BootstrapError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    click.echo(f"project:       {st['project_id']}")
    click.echo(f"running:       {st['running']}")
    click.echo(f"mode:          {st['mode'] or '-'}")
    click.echo(f"restart_count: {st['restart_count'] if st['restart_count'] is not None else '-'}")
    click.echo(f"state:         {st['state'] or '-'}")
    click.echo(f"supervised:    {st['supervised']}")


@cli.command("ps", help="List running project containers.")
def _cli_ps() -> None:
    rows = cmd_ps()
    if not rows:
        click.echo("(no project containers running)")
        return
    click.echo(f"{'PROJECT':24} {'MODE':12} {'STARTED':24}")
    for r in rows:
        click.echo(
            f"{r['project_id']:24} {r['mode']:12} {r['started_at']:24}"
        )


@cli.command("login", help="Establish the Claude subscription credential store.")
@click.option(
    "--fresh",
    is_flag=True,
    default=False,
    help="Ignore any host login and log in fresh inside a container.",
)
def _cli_login(fresh: bool) -> None:
    home = _asdd_home_from_env()
    try:
        source = cmd_login(asdd_home=home, fresh=fresh)
    except BootstrapError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    except project_container.ProjectContainerError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    click.echo(f"logged in (source: {source})")


@cli.command("logout", help="Remove the Claude subscription credential store.")
def _cli_logout() -> None:
    home = _asdd_home_from_env()
    removed = cmd_logout(asdd_home=home)
    click.echo("logged out" if removed else "already logged out")


@cli.command("whoami", help="Show Claude subscription auth status (no network call).")
def _cli_whoami() -> None:
    home = _asdd_home_from_env()
    st = cmd_whoami(asdd_home=home)
    if not st.logged_in:
        click.echo("not logged in — run `asdd login`", err=True)
        sys.exit(1)
    click.echo(f"logged_in: true (source: {st.source or 'unknown'})")
    if st.identity:
        click.echo(f"identity: {st.identity}")
    if st.expiry:
        click.echo(f"expiry: {st.expiry}")


@cli.group("secrets", help="Manage per-project encrypted secrets (SOPS+age).")
def _cli_secrets() -> None:
    pass


@_cli_secrets.command("add", help="Add or update one secret for a project.")
@click.argument("project_id")
@click.argument("key")
@click.option(
    "--value",
    default=None,
    help="Secret value. If omitted, the operator is prompted (hidden input).",
)
@click.option(
    "--recipient",
    default=None,
    help="Age recipient (public key) for first-time encryption. "
    "Falls back to $SOPS_AGE_RECIPIENTS if unset.",
)
def _cli_secrets_add(
    project_id: str, key: str, value: str | None, recipient: str | None
) -> None:
    home = _asdd_home_from_env()
    if value is None:
        value = click.prompt(
            f"value for {key}",
            hide_input=True,
            confirmation_prompt=True,
        )
    try:
        cmd_secrets_add(
            asdd_home=home,
            project_id=project_id,
            key=key,
            value=value,
            recipient=recipient,
        )
    except BootstrapError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    click.echo(f"secret {key!r} added to project {project_id!r}")


@_cli_secrets.command("remove", help="Remove one secret from a project.")
@click.argument("project_id")
@click.argument("key")
def _cli_secrets_remove(project_id: str, key: str) -> None:
    home = _asdd_home_from_env()
    try:
        removed = cmd_secrets_remove(asdd_home=home, project_id=project_id, key=key)
    except BootstrapError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    if removed:
        click.echo(f"secret {key!r} removed from project {project_id!r}")
    else:
        click.echo(f"secret {key!r} was not present in project {project_id!r}")


@_cli_secrets.command("list", help="List secret keys for a project (values NOT revealed).")
@click.argument("project_id")
def _cli_secrets_list(project_id: str) -> None:
    home = _asdd_home_from_env()
    try:
        keys = cmd_secrets_list(asdd_home=home, project_id=project_id)
    except BootstrapError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    if not keys:
        click.echo(f"(no secrets configured for project {project_id!r})")
        return
    for k in keys:
        click.echo(k)


@cli.command(
    "dispatch",
    help="Run one autonomous-mode job inside a project's container (spec 008 US5).",
)
@click.argument("project_id")
@click.argument("job_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--api-key",
    "use_api_key",
    is_flag=True,
    default=False,
    help="Bill this run to $ANTHROPIC_API_KEY instead of the subscription "
    "(also honours ASDD_USE_API_KEY=1). Suppresses the credential-store mount.",
)
def _cli_dispatch(project_id: str, job_path: Path, use_api_key: bool) -> None:
    home = _asdd_home_from_env()
    if os.environ.get("ASDD_USE_API_KEY") == "1":
        use_api_key = True
    try:
        result_file = cmd_dispatch(
            asdd_home=home,
            project_id=project_id,
            job_path=job_path,
            use_api_key=use_api_key,
        )
    except BootstrapError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    except project_container.ProjectContainerError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    click.echo(f"result: {result_file}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
