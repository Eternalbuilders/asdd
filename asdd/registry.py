"""Project registry: load + validate + query (T010).

Loads ``${ASDD_HOME}/_state/projects.yml`` via PyYAML, validates against
``projects.yml.schema.json``, and exposes a small typed API.

Reads only. The kernel never writes the registry; only the operator (via
``asdd`` CLI subcommands or by direct edit) writes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from asdd._schemas import RegistryLoadError, validate_registry


class _StringTimestampLoader(yaml.SafeLoader):
    """SafeLoader variant that leaves ISO-8601 timestamps as strings.

    The default SafeLoader converts YAML timestamps to ``datetime`` objects,
    but our JSON Schema expects strings (``format: date-time``). We override
    the constructor for tag:yaml.org,2002:timestamp to return the raw string.
    """


def _construct_timestamp_as_string(loader: yaml.Loader, node: yaml.Node) -> str:
    return node.value


_StringTimestampLoader.add_constructor(
    "tag:yaml.org,2002:timestamp",
    _construct_timestamp_as_string,
)

LifecycleState = Literal["active", "paused", "archived", "unreachable", "unhealthy"]


@dataclass(frozen=True)
class Project:
    """A single registered ASDD project. See data-model.md § 1.1."""

    id: str
    name: str
    workspace_path: str
    git_remote: str | None
    default_branch: str
    lifecycle_state: LifecycleState
    created_at: str
    last_checked_at: str
    description: str | None

    @property
    def workspace(self) -> Path:
        return Path(self.workspace_path)


@dataclass(frozen=True)
class Registry:
    """The parsed contents of projects.yml. See data-model.md § 1.2."""

    version: int
    default_project_id: str
    projects: tuple[Project, ...]


def _project_from_dict(d: dict) -> Project:
    return Project(
        id=d["id"],
        name=d["name"],
        workspace_path=d["workspace_path"],
        git_remote=d.get("git_remote"),
        default_branch=d["default_branch"],
        lifecycle_state=d["lifecycle_state"],
        created_at=d["created_at"],
        last_checked_at=d["last_checked_at"],
        description=d.get("description"),
    )


def load(path: Path) -> Registry:
    """Read and validate the registry file at ``path``.

    Raises:
        RegistryLoadError: if the file is missing, unreadable, malformed YAML,
            schema-invalid, or violates a cross-row invariant
            (duplicate ID or duplicate workspace_path).
    """
    try:
        with path.open() as f:
            raw = yaml.load(f, Loader=_StringTimestampLoader)
    except FileNotFoundError as e:
        raise RegistryLoadError(f"projects.yml not found at {path}") from e
    except yaml.YAMLError as e:
        raise RegistryLoadError(f"projects.yml malformed YAML: {e}") from e

    if not isinstance(raw, dict):
        raise RegistryLoadError("projects.yml top-level must be a mapping")

    validate_registry(raw)

    projects = tuple(_project_from_dict(p) for p in raw["projects"])

    # Cross-row invariants from data-model.md § 1.1
    ids = [p.id for p in projects]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise RegistryLoadError(f"projects.yml has duplicate ids: {dupes}")
    paths = [p.workspace_path for p in projects]
    if len(paths) != len(set(paths)):
        dupes = sorted({p for p in paths if paths.count(p) > 1})
        raise RegistryLoadError(f"projects.yml has duplicate workspace_path: {dupes}")

    return Registry(
        version=raw["version"],
        default_project_id=raw["default_project_id"],
        projects=projects,
    )


def find(registry: Registry, project_id: str) -> Project | None:
    """Return the project with the given id, or None."""
    for p in registry.projects:
        if p.id == project_id:
            return p
    return None


def active_projects(registry: Registry) -> list[Project]:
    """Return projects whose lifecycle_state is ``active``."""
    return [p for p in registry.projects if p.lifecycle_state == "active"]


__all__ = [
    "Project",
    "Registry",
    "RegistryLoadError",
    "load",
    "find",
    "active_projects",
]
