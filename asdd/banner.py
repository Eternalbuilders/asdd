"""Session-start stale-tool banner (spec 002).

Rendered host-side before the asdd CLI attaches into the container. One line
per stale tool, ≤ 78 columns, ANSI-colorized only when stderr is a TTY and
``NO_COLOR`` is unset. Multiple-tool case folds to a summary line beyond 5.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

MAX_COLS = 78
MAX_DETAILED_LINES = 5
MARKER = "⓿"  # "⓿" — negative-circled digit zero

# ANSI escapes; emitted only when should_color() returns True.
_DIM = "\x1b[2m"
_BOLD = "\x1b[1m"
_EMBER = "\x1b[33m"  # yellow-ish; close to brand ember at the terminal palette level
_RESET = "\x1b[0m"


@dataclass(frozen=True)
class BannerLine:
    """One stale tool to surface in the banner."""

    tool: str
    installed: str
    latest: str
    project_id: str


def should_color() -> bool:
    """Honour ``NO_COLOR`` and only colorize when stderr is a real TTY."""
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stderr.isatty()
    except (ValueError, AttributeError):
        return False


def render(
    stale: list[BannerLine],
    *,
    color: bool | None = None,
) -> list[str]:
    """Render the banner; return zero or more lines, each without a trailing newline.

    Empty input → empty output (no banner). Sorted alphabetically by tool name.
    Caps at ``MAX_DETAILED_LINES`` detailed lines; overflow folds to a summary.
    """
    if not stale:
        return []
    if color is None:
        color = should_color()

    sorted_stale = sorted(stale, key=lambda s: s.tool)
    detailed = sorted_stale[:MAX_DETAILED_LINES]
    overflow = sorted_stale[MAX_DETAILED_LINES:]

    out: list[str] = []
    for line in detailed:
        out.append(_render_one(line, color=color))
    if overflow:
        # Use the first overflow line's project to suggest `asdd versions <project>`.
        proj = overflow[0].project_id
        msg = (
            f"{MARKER}  {len(overflow)} more tools have updates — "
            f"run `asdd versions {proj}` to see them"
        )
        out.append(_paint(msg, color=color))
    return out


def _render_one(line: BannerLine, *, color: bool) -> str:
    cmd = f"asdd upgrade {line.tool} {line.project_id}"
    # Try the full form first.
    full = (
        f"{MARKER}  {line.tool} {line.installed} → {line.latest} "
        f"available — run `{cmd}` to apply"
    )
    if _visible_len(full) <= MAX_COLS:
        return _paint(full, color=color, command=cmd)
    # Short form drops the explicit version arrow.
    short = (
        f"{MARKER}  {line.tool} — update available — "
        f"run `{cmd}` to apply"
    )
    return _paint(short, color=color, command=cmd)


def _paint(text: str, *, color: bool, command: str | None = None) -> str:
    if not color:
        return text
    out = text
    out = out.replace(MARKER, f"{_EMBER}{MARKER}{_RESET}")
    if command is not None:
        out = out.replace(f"`{command}`", f"{_EMBER}`{command}`{_RESET}")
    out = out.replace("available", f"{_BOLD}available{_RESET}")
    return out


def _visible_len(s: str) -> int:
    """Approximate visible length (counts the marker as one column)."""
    # The marker glyph is conventionally narrow at most terminal cell widths.
    return len(s)
