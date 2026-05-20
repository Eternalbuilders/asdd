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

from asdd import lifecycle, project_container, secrets, workspace
from asdd.registry import Project
from asdd._schemas import validate_registry

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

    project_container.ensure_image_built()
    project_container.assert_not_running(project_id)

    project_secrets = _decrypt_project_secrets(row)

    pc_obj = project_container.ProjectContainer(
        project_id=project_id,
        mode="interactive",
        workspace_path=Path(row["workspace_path"]),
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


def cmd_dispatch(*, asdd_home: Path, project_id: str, job_path: Path) -> Path:
    """Run one autonomous-mode job inside a project's container (spec 008 US5 / FR-009).

    Starts the project's container in autonomous mode (no operator host
    credentials), invokes the in-image `asdd-run-job` shim against the
    job-note file, captures the result to the project's `results/` dir,
    and stops the container.

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

    project_container.ensure_image_built()
    project_container.assert_not_running(project_id)

    project_secrets = _decrypt_project_secrets(row)

    pc_obj = project_container.ProjectContainer(
        project_id=project_id,
        mode="autonomous",
        workspace_path=workspace_path,
    )
    project_container.start_container(pc_obj, extra_env=project_secrets)
    try:
        in_container_path = f"{project_container.IN_CONTAINER_WORKDIR}/{job_rel}"
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
            raise project_container.ProjectContainerError(
                f"asdd-run-job exited {result.returncode} for {job_rel}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
    finally:
        project_container.stop_container(project_id)

    result_file = workspace_path / "results" / f"{job_path.stem}.result.md"
    return result_file


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
# Click CLI surface
# ---------------------------------------------------------------------------


def _asdd_home_from_env() -> Path:
    h = os.environ.get("ASDD_HOME")
    if h:
        return Path(h)
    return Path.home() / "Code" / "asdd"


@click.group(help="ASDD platform management CLI.")
@click.version_option(package_name="controlvault-agent")
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
def _cli_dispatch(project_id: str, job_path: Path) -> None:
    home = _asdd_home_from_env()
    try:
        result_file = cmd_dispatch(
            asdd_home=home, project_id=project_id, job_path=job_path
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
