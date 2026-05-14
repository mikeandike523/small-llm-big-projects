from __future__ import annotations

import re

EOL_CHOICES = ["lf", "crlf", "cr"]

_EOL_MAP = {
    "lf": "\n",
    "crlf": "\r\n",
    "cr": "\r",
}


def check_eol(text: str) -> str:
    """Return a human-readable report of line ending usage in *text*.

    Counts are mutually exclusive:
      - CRLF  counted first (\\r\\n pairs)
      - LF    \\n not preceded by \\r
      - CR    \\r not followed by \\n

    Note: bare \\r (CR alone) is NOT treated as a line terminator by this
    toolkit.  It is a regular character used in terminal output (progress
    bars, spinners, etc.) that happens to appear in captured text.  It is
    reported here for visibility but is not modified by line operations.
    """
    crlf_count = text.count("\r\n")
    lf_count = len(re.findall(r"(?<!\r)\n", text))
    cr_count = len(re.findall(r"\r(?!\n)", text))

    total = crlf_count + lf_count + cr_count

    if total == 0:
        return "No line endings found."

    present: list[str] = []
    if crlf_count:
        present.append(f"  CRLF (\\r\\n): {crlf_count}")
    if lf_count:
        present.append(f"  LF   (\\n):   {lf_count}")
    if cr_count:
        present.append(
            f"  CR   (\\r):   {cr_count}"
            "  (bare carriage return -- treated as a character, not a line terminator)"
        )

    verdict = "uniform" if len(present) == 1 else "mixed"
    lines = [f"Total line endings: {total} ({verdict})"] + present
    return "\n".join(lines)


def normalize_eol(text: str, eol: str) -> str:
    """Normalize line endings in *text* to *eol* (one of: lf, crlf, cr).

    Only CRLF (\\r\\n) and LF (\\n) are recognised as line terminators.
    Bare \\r is NOT a line terminator and is left unchanged.

    Raises ValueError for an unknown eol value.
    """
    target = _EOL_MAP.get(eol)
    if target is None:
        raise ValueError(
            f"Unknown EOL type: {eol!r}. Choose from: {', '.join(EOL_CHOICES)}"
        )

    # Collapse CRLF to plain LF, then convert LF to the target style.
    # Bare \r is intentionally NOT touched -- it is a character, not a terminator.
    text = text.replace("\r\n", "\n")
    if target != "\n":
        text = text.replace("\n", target)
    return text
