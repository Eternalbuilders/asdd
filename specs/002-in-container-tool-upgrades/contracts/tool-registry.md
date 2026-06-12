# Contract: Tool registry + driver interface

**Feature**: 002-in-container-tool-upgrades
**Status**: New.
**Location**: `asdd/tools.py`.

## Tool registry

Module-level `TOOLS: dict[str, ManagedTool]` declares every tool the system manages. Adding a tool = adding one entry, plus a driver if the install method is new.

```python
@dataclass(frozen=True)
class ManagedTool:
    name: str                                              # registry key; matches the binary
    driver_method: Literal["npm-global", "github-release", "astral-install"]
    source_id: str                                         # per-driver source identifier
    binary_name: str                                       # basename of the installed binary

TOOLS: dict[str, ManagedTool] = {
    "claude": ManagedTool(
        name="claude",
        driver_method="npm-global",
        source_id="@anthropic-ai/claude-code",
        binary_name="claude",
    ),
    "gh": ManagedTool(
        name="gh",
        driver_method="github-release",
        source_id="cli/cli",
        binary_name="gh",
    ),
    "uv": ManagedTool(
        name="uv",
        driver_method="astral-install",
        source_id="astral-sh/uv",
        binary_name="uv",
    ),
}
```

## Driver interface

Each `driver_method` value corresponds to a `ToolDriver` implementation. Drivers are pure functions over a path namespace + an HTTP client — no global state.

```python
class ToolDriver(Protocol):
    """
    A driver owns the install/uninstall/version mechanics for one install method.
    All paths passed in are inside the per-tool root: <overlay>/<tool_name>/.
    """

    method: str  # matches ManagedTool.driver_method

    def installed_version(self, tool: ManagedTool, root: Path) -> str | None:
        """
        Inspect <root>/versions/ for the currently-symlinked binary.
        Returns the version string or None if nothing is installed in the overlay.
        """

    def latest_version(self, tool: ManagedTool, *, timeout: float) -> str | None:
        """
        Single HTTPS round-trip to the upstream registry.
        Returns the version string or None on timeout / failure.
        """

    def install(
        self,
        tool: ManagedTool,
        root: Path,
        version: str,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> InstallResult:
        """
        Stage <root>/incoming/<version>/ with the new install, then atomically
        rename to <root>/versions/<version>/.

        Caller is responsible for the bin/ symlink update and the manifest write.
        """

    def uninstall(self, tool: ManagedTool, root: Path, version: str) -> None:
        """
        rm -rf <root>/versions/<version>/. Idempotent.
        """
```

```python
@dataclass(frozen=True)
class InstallResult:
    version: str                 # actually-installed version (canonical form)
    size_bytes: int              # disk used by <root>/versions/<version>/
```

## `npm-global` driver

| Operation | Implementation |
|---|---|
| `installed_version(root)` | Read `root/versions/<current>/lib/node_modules/<package>/package.json`. Return `.version`. The "current" comes from the manifest. |
| `latest_version(timeout)` | `GET https://registry.npmjs.org/-/package/@anthropic-ai/claude-code/dist-tags` → `.latest`. |
| `install(root, version)` | `mkdir -p root/incoming/<version>` → `npm install -g --prefix=root/incoming/<version> @anthropic-ai/claude-code@<version>` → `mv root/incoming/<version> root/versions/<version>`. |
| `uninstall(root, version)` | `rm -rf root/versions/<version>`. |

The `npm install` runs inside the container via `docker exec -u asdd <container> npm install -g --prefix=...`. Network goes through the container.

## `github-release` driver

| Operation | Implementation |
|---|---|
| `installed_version(root)` | Run the existing `root/bin/<binary> --version` and parse the first numeric token. |
| `latest_version(timeout)` | `GET https://api.github.com/repos/<owner>/<repo>/releases/latest` → strip leading `v` from `.tag_name`. |
| `install(root, version)` | Detect arch via `dpkg --print-architecture` inside the container. Build the asset name (e.g., `gh_2.95.0_linux_arm64.tar.gz`). `curl -fsSL` the release tarball to `root/incoming/<version>/dl.tar.gz`. `tar -xzf` it. Extract the relevant binary into `root/incoming/<version>/bin/`. Discard the tarball. Atomic rename. |
| `uninstall(root, version)` | `rm -rf root/versions/<version>`. |

## `astral-install` driver

| Operation | Implementation |
|---|---|
| `installed_version(root)` | Run `root/<binary> --version` and parse. |
| `latest_version(timeout)` | `GET https://api.github.com/repos/astral-sh/uv/releases/latest` → strip leading `v`. |
| `install(root, version)` | Download the platform-appropriate tarball from `https://github.com/astral-sh/uv/releases/download/<version>/uv-<target>.tar.gz`. Extract `uv` to `root/incoming/<version>/uv`. Atomic rename. (We avoid running the astral install.sh script every upgrade.) |
| `uninstall(root, version)` | `rm -rf root/versions/<version>`. |

## Wiring (orchestrator-side, not in the driver)

The orchestrator (`asdd/bootstrap.py:cmd_upgrade`) handles, in order:

1. Lock acquisition (`asdd/tool_manifest.py:acquire_lock`).
2. Manifest read (`asdd/tool_manifest.py:load`).
3. Latest-version probe with timeout (cached via `asdd/version_check.py`).
4. Driver `install()` — actual file work.
5. Aggregate `bin/` symlink update.
6. Manifest write (`asdd/tool_manifest.py:save`).
7. History truncation + eviction (`uninstall` of the third-oldest version).
8. Optional `--reload` (`asdd/project_container.py:bounce_persistent_claude`).
9. Lock release.

Drivers do not touch `bin/<tool>`, the manifest, or the history — that's all orchestrator work. This keeps drivers simple and easy to unit-test (mock subprocess + urllib).

## Adding a new tool

1. Pick an existing `driver_method` if one fits, OR add a new one (new class + protocol implementation).
2. Add a `ManagedTool(...)` entry to `TOOLS`.
3. Add the install command to `Dockerfile.project` so the baseline includes it.
4. Update `docker/files/asdd-baseline-versions.json` (generated at build time — no manual entry needed).
5. Add a test in `tests/unit/test_tools.py` exercising the new driver's installed/latest/install paths with mocks.
6. Update `USER_GUIDE.md` "Keep your tools current" with the new tool.

No core asdd code outside `asdd/tools.py` should need changes.

## What drivers do NOT do

- Drivers do not write the manifest.
- Drivers do not update `bin/<tool>`.
- Drivers do not bounce any persistent process.
- Drivers do not retry on failure (the CLI decides retry policy).
- Drivers do not log; they raise structured exceptions and the orchestrator logs.
