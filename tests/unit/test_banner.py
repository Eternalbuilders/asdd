"""Unit tests for asdd/banner.py — spec 002 Phase 2."""

from __future__ import annotations

from asdd import banner


def _line(tool: str, installed: str, latest: str) -> banner.BannerLine:
    return banner.BannerLine(tool=tool, installed=installed, latest=latest, project_id="dev")


def test_empty_input_returns_no_lines() -> None:
    assert banner.render([]) == []


def test_single_stale_tool_renders_one_line() -> None:
    out = banner.render([_line("claude", "2.1.150", "2.1.151")], color=False)
    assert len(out) == 1
    assert "claude" in out[0]
    assert "2.1.150" in out[0]
    assert "2.1.151" in out[0]
    assert "asdd upgrade claude dev" in out[0]


def test_lines_are_sorted_alphabetically() -> None:
    out = banner.render(
        [
            _line("uv", "0.4.10", "0.4.12"),
            _line("claude", "2.1.150", "2.1.151"),
            _line("gh", "2.94.0", "2.95.0"),
        ],
        color=False,
    )
    assert len(out) == 3
    assert "claude" in out[0]
    assert "gh" in out[1]
    assert "uv" in out[2]


def test_more_than_five_tools_folds_into_summary() -> None:
    many = [
        _line(f"tool{i}", "1.0.0", "1.0.1")
        for i in range(7)
    ]
    out = banner.render(many, color=False)
    # 5 detailed + 1 summary = 6 lines total.
    assert len(out) == 6
    assert "2 more tools" in out[-1]
    assert "asdd versions dev" in out[-1]


def test_color_off_omits_ansi_escapes() -> None:
    out = banner.render([_line("claude", "2.1.150", "2.1.151")], color=False)
    assert "\x1b[" not in out[0]


def test_color_on_includes_ansi_escapes() -> None:
    out = banner.render([_line("claude", "2.1.150", "2.1.151")], color=True)
    assert "\x1b[" in out[0]


def test_long_tool_name_falls_back_to_short_form() -> None:
    # Force the long form to exceed 78 cols by using a giant tool name.
    long_name = "a-very-very-very-very-very-very-long-tool-name"
    out = banner.render(
        [_line(long_name, "1.0.0", "1.0.1")],
        color=False,
    )
    # Short form contains "update available" but NOT "→".
    assert "update available" in out[0]
    assert "→" not in out[0]


def test_should_color_honors_no_color(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("NO_COLOR", "1")
    assert banner.should_color() is False


def test_should_color_when_no_tty(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("NO_COLOR", raising=False)
    # The pytest stderr is a normal stream, not a real TTY — should_color
    # falls back to False.
    assert banner.should_color() is False
