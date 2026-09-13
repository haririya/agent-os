from __future__ import annotations

from datetime import UTC, datetime

from agentos.engine.steps.inject_time_prefix import format_time_prefix, stamp
from agentos.memory.turn_capture import _strip_time_prefix


def test_format_time_prefix_renders_expected_format() -> None:
    now = datetime(2026, 9, 13, 15, 30, tzinfo=UTC)
    rendered = format_time_prefix(now, "UTC")
    assert rendered == "[2026-09-13T15:30+00:00 Sun UTC]"


def test_stamp_prepends_prefix() -> None:
    now = datetime(2026, 9, 13, 15, 30, tzinfo=UTC)
    result = stamp("Hello agent", now, "UTC")
    assert result == "[2026-09-13T15:30+00:00 Sun UTC]\nHello agent"


def test_stamp_is_idempotent_with_standard_tz() -> None:
    now = datetime(2026, 9, 13, 15, 30, tzinfo=UTC)
    stamped_once = stamp("Hello agent", now, "America/New_York")
    stamped_twice = stamp(stamped_once, now, "America/New_York")
    assert stamped_twice == stamped_once


def test_stamp_is_idempotent_with_multi_word_windows_tz() -> None:
    now = datetime(2026, 9, 13, 15, 30, tzinfo=UTC)
    for tz in (
        "Eastern Standard Time",
        "SE Asia Standard Time",
        "W. Europe Standard Time",
        "India Standard Time",
    ):
        stamped_once = stamp("Hello agent", now, tz)
        assert isinstance(stamped_once, str)
        assert stamped_once.startswith(f"[2026-09-13T15:30+00:00 Sun {tz}]\n")
        stamped_twice = stamp(stamped_once, now, tz)
        assert stamped_twice == stamped_once


def test_stamp_is_idempotent_with_crlf_line_endings() -> None:
    now = datetime(2026, 9, 13, 15, 30, tzinfo=UTC)
    stamped_crlf = "[2026-09-13T15:30+00:00 Sun UTC]\r\nHello agent"
    stamped_again = stamp(stamped_crlf, now, "UTC")
    assert stamped_again == stamped_crlf


def test_stamp_ignores_empty_and_non_string() -> None:
    now = datetime(2026, 9, 13, 15, 30, tzinfo=UTC)
    assert stamp("", now, "UTC") == ""
    assert stamp("   ", now, "UTC") == "   "
    assert stamp(None, now, "UTC") is None
    assert stamp(12345, now, "UTC") == 12345


def test_turn_capture_strip_time_prefix_multi_word_and_crlf() -> None:
    now = datetime(2026, 9, 13, 15, 30, tzinfo=UTC)
    stamped_est = stamp("My prompt text", now, "Eastern Standard Time")
    assert isinstance(stamped_est, str)
    assert _strip_time_prefix(stamped_est) == "My prompt text"

    stamped_crlf = "[2026-09-13T15:30+00:00 Sun W. Europe Standard Time]\r\nMy prompt text"
    assert _strip_time_prefix(stamped_crlf) == "My prompt text"
