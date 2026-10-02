from src.utils.text_truncation import truncate_long_lines


def test_short_lines_pass_through_unchanged() -> None:
    text = "line one\nline two\n"
    assert truncate_long_lines(text, 500) == text


def test_long_line_is_truncated_with_marker() -> None:
    assert truncate_long_lines("x" * 600, 500) == "x" * 500 + "[... 100 more chars]"


def test_only_long_lines_are_affected() -> None:
    text = "short\n" + "y" * 700 + "\nalso short"
    lines = truncate_long_lines(text, 500).split("\n")
    assert lines == ["short", "y" * 500 + "[... 200 more chars]", "also short"]


def test_crlf_line_endings_round_trip() -> None:
    text = "z" * 600 + "\r\nok\r\n"
    out = truncate_long_lines(text, 500)
    assert out == "z" * 500 + "[... 100 more chars]\r\nok\r\n"


def test_zero_disables_truncation() -> None:
    long = "q" * 1000
    assert truncate_long_lines(long, 0) == long
