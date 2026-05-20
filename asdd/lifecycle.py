"""Project lifecycle state machine (T012).

Pure functions over the five-state graph from data-model.md § 1.1. No I/O,
no side effects. The kernel and CLI use these to validate transitions
before mutating the registry.
"""

from __future__ import annotations

from typing import Literal

LifecycleState = Literal["active", "paused", "archived", "unreachable", "unhealthy"]
AutoEvent = Literal["workspace_missing", "baseline_broken", "doctor_ok"]

# Operator-driven transitions (R11 in research.md).
_OPERATOR_EDGES: frozenset[tuple[LifecycleState, LifecycleState]] = frozenset(
    {
        ("active", "paused"),
        ("paused", "active"),
        ("active", "archived"),
        ("paused", "archived"),
        # Manual revival of archived requires direct registry edit; we allow it.
        ("archived", "active"),
    }
)

# Auto-detected events; the platform overlay sets these (kernel does not write
# projects.yml directly per Principle VI, but the state-machine API is here for
# planners and tests).
_AUTO_TRANSITIONS: dict[tuple[LifecycleState, AutoEvent], LifecycleState] = {
    ("active", "workspace_missing"): "unreachable",
    ("paused", "workspace_missing"): "unreachable",
    ("active", "baseline_broken"): "unhealthy",
    ("paused", "baseline_broken"): "unhealthy",
    ("unreachable", "doctor_ok"): "active",
    ("unhealthy", "doctor_ok"): "active",
}


def can_transition(from_state: LifecycleState, to_state: LifecycleState) -> bool:
    """Whether an operator may transition between these two states."""
    return (from_state, to_state) in _OPERATOR_EDGES


def next_state_on_auto_event(state: LifecycleState, event: AutoEvent) -> LifecycleState:
    """Apply an auto-event; return the next state (possibly identical to the input).

    Auto-events that do not apply to the current state are no-ops. (E.g.,
    ``workspace_missing`` while already ``unreachable``.)
    """
    return _AUTO_TRANSITIONS.get((state, event), state)


def is_terminal(state: LifecycleState) -> bool:
    """Whether the state is terminal under auto-events.

    ``archived`` is terminal under auto-events; the only way out is the
    explicit operator edge (``archived → active``).
    """
    return state == "archived"


__all__ = [
    "LifecycleState",
    "AutoEvent",
    "can_transition",
    "next_state_on_auto_event",
    "is_terminal",
]
