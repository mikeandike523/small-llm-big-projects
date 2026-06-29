from src.tools import _truncate_columns
from src.tools.config import TOOL_OUTPUT_MAX_COLUMNS
from src.utils.text_truncation import truncate_long_lines


def test_default_limit_is_500() -> None:
    assert TOOL_OUTPUT_MAX_COLUMNS == 500


def test_short_lines_pass_through_unchanged() -> None:
    text = "line one\nline two\n"
    assert _truncate_columns(text) == text


def test_long_line_is_truncated_with_marker() -> None:
    long = "x" * 600
    out = _truncate_columns(long)
    assert out.startswith("x" * TOOL_OUTPUT_MAX_COLUMNS)
    assert out == "x" * TOOL_OUTPUT_MAX_COLUMNS + "[... 100 more bytes]"


def test_only_long_lines_are_affected() -> None:
    text = "short\n" + "y" * 700 + "\nalso short"
    lines = _truncate_columns(text).split("\n")
    assert lines[0] == "short"
    assert lines[1] == "y" * TOOL_OUTPUT_MAX_COLUMNS + "[... 200 more bytes]"
    assert lines[2] == "also short"


def test_crlf_line_endings_round_trip() -> None:
    text = "z" * 600 + "\r\nok\r\n"
    out = _truncate_columns(text)
    assert out == "z" * TOOL_OUTPUT_MAX_COLUMNS + "[... 100 more bytes]\r\nok\r\n"


def test_zero_disables_truncation() -> None:
    long = "q" * 1000
    assert truncate_long_lines(long, 0) == long


def test_non_string_passthrough() -> None:
    assert _truncate_columns(None) is None  # type: ignore[arg-type]
