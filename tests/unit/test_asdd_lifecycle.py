"""Unit tests for asdd/lifecycle.py state machine (T026)."""

from __future__ import annotations

import pytest

from asdd.lifecycle import can_transition, is_terminal, next_state_on_auto_event


class TestOperatorTransitions:
    def test_pause_and_resume(self) -> None:
        assert can_transition("active", "paused")
        assert can_transition("paused", "active")

    def test_archive_from_active_and_paused(self) -> None:
        assert can_transition("active", "archived")
        assert can_transition("paused", "archived")

    def test_archive_to_active_allowed_manually(self) -> None:
        assert can_transition("archived", "active")

    def test_no_self_loops(self) -> None:
        for s in ("active", "paused", "archived", "unreachable", "unhealthy"):
            assert not can_transition(s, s), f"self-loop should be forbidden: {s}"

    @pytest.mark.parametrize(
        "bad",
        [
            ("active", "unreachable"),  # operator can't directly mark unreachable
            ("active", "unhealthy"),  # auto-event sets these, not operator
            ("paused", "unreachable"),
            ("archived", "paused"),  # archived → paused not allowed; revive directly to active
            ("unreachable", "active"),  # doctor event sets this, not operator
        ],
    )
    def test_invalid_operator_transitions(self, bad: tuple[str, str]) -> None:
        assert not can_transition(*bad), f"should be invalid: {bad}"


class TestAutoEvents:
    def test_workspace_missing_marks_unreachable(self) -> None:
        assert next_state_on_auto_event("active", "workspace_missing") == "unreachable"
        assert next_state_on_auto_event("paused", "workspace_missing") == "unreachable"

    def test_baseline_broken_marks_unhealthy(self) -> None:
        assert next_state_on_auto_event("active", "baseline_broken") == "unhealthy"

    def test_doctor_ok_restores_to_active(self) -> None:
        assert next_state_on_auto_event("unreachable", "doctor_ok") == "active"
        assert next_state_on_auto_event("unhealthy", "doctor_ok") == "active"

    def test_no_op_events(self) -> None:
        # doctor_ok on a healthy active project is a no-op
        assert next_state_on_auto_event("active", "doctor_ok") == "active"
        # workspace_missing on archived is a no-op (archived is terminal)
        assert next_state_on_auto_event("archived", "workspace_missing") == "archived"


class TestTerminal:
    def test_only_archived_is_terminal(self) -> None:
        assert is_terminal("archived")
        for s in ("active", "paused", "unreachable", "unhealthy"):
            assert not is_terminal(s)
