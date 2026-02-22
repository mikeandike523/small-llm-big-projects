from __future__ import annotations

from src.config.text import LINE_NUMBERING_DELIMETER


def add_line_numbers(text: str, *, start_line: int = 1, delimiter: str | None = None) -> str:
    if text == "":
        return ""

    lines = text.splitlines(keepends=True)
    if not lines:
        return ""

    sep = LINE_NUMBERING_DELIMETER if delimiter is None else delimiter
    max_line_number = start_line + len(lines) - 1
    line_no_width = len(str(max_line_number))

    return "".join(
        f"{str(line_no).rjust(line_no_width)}{sep}{line}"
        for line_no, line in enumerate(lines, start=start_line)
    )
