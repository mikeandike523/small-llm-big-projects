from __future__ import annotations

from src.config.text import LINE_NUMBERING_DELIMETER


def add_line_numbers(text: str, *, start_line: int = 1) -> str:
    if text == "":
        return ""

    lines = text.splitlines(keepends=True)
    if not lines:
        return ""

    max_line_number = start_line + len(lines) - 1
    line_no_width = len(str(max_line_number))

    return "".join(
        f"{str(line_no).rjust(line_no_width)}{LINE_NUMBERING_DELIMETER}{line}"
        for line_no, line in enumerate(lines, start=start_line)
    )
