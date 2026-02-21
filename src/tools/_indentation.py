from __future__ import annotations

from collections import Counter

INDENT_TARGET_CHOICES = ["tabs", "spaces"]
DEFAULT_SPACES_PER_TAB = 4


def check_indentation(text: str) -> str:
    """Return a human-readable report of indentation style in *text*.

    Only leading whitespace (before the first non-whitespace character) on
    each non-blank line is examined.
    """
    tab_lines = 0
    space_lines = 0
    mixed_lines = 0  # leading whitespace contains both tabs and spaces
    space_widths: Counter[int] = Counter()

    for line in text.splitlines():
        if not line.strip():
            continue  # skip blank / whitespace-only lines

        stripped = line.lstrip()
        leading = line[: len(line) - len(stripped)]

        if not leading:
            continue  # no indentation on this line

        has_tabs = "\t" in leading
        has_spaces = " " in leading

        if has_tabs and has_spaces:
            mixed_lines += 1
        elif has_tabs:
            tab_lines += 1
        else:
            space_lines += 1
            space_widths[len(leading)] += 1

    indented = tab_lines + space_lines + mixed_lines

    if indented == 0:
        return "No indentation found."

    if tab_lines > 0 and space_lines == 0 and mixed_lines == 0:
        verdict = "tabs"
    elif space_lines > 0 and tab_lines == 0 and mixed_lines == 0:
        verdict = "spaces"
    else:
        verdict = "mixed"

    lines_out = [
        f"Indented lines: {indented}",
        f"Style: {verdict}",
    ]
    if tab_lines:
        lines_out.append(f"  Tab-indented:   {tab_lines}")
    if space_lines:
        lines_out.append(f"  Space-indented: {space_lines}")
        if space_widths:
            top = space_widths.most_common(3)
            widths_str = ", ".join(f"{w} spaces ({c}x)" for w, c in top)
            lines_out.append(f"  Most common indent widths: {widths_str}")
    if mixed_lines:
        lines_out.append(f"  Mixed (tabs+spaces in leading): {mixed_lines}")

    return "\n".join(lines_out)


def convert_indentation(text: str, to: str, spaces_per_tab: int = DEFAULT_SPACES_PER_TAB) -> str:
    """Rewrite only the leading whitespace on each line to use *to* style.

    Args:
        text: source text (any line-ending style; endings are preserved).
        to: "tabs" or "spaces".
        spaces_per_tab: width of a tab stop in spaces (used in both directions).

    Raises:
        ValueError: for an unknown *to* value or non-positive *spaces_per_tab*.
    """
    if to not in INDENT_TARGET_CHOICES:
        raise ValueError(
            f"Unknown indentation target: {to!r}. Choose from: {', '.join(INDENT_TARGET_CHOICES)}"
        )
    if spaces_per_tab < 1:
        raise ValueError(f"spaces_per_tab must be >= 1, got {spaces_per_tab}")

    result: list[str] = []

    for line in text.splitlines(keepends=True):
        stripped = line.lstrip(" \t")
        leading = line[: len(line) - len(stripped)]

        if not leading:
            result.append(line)
            continue

        # Expand any mixed tabs/spaces to a canonical space count first.
        expanded = leading.replace("\t", " " * spaces_per_tab)

        if to == "spaces":
            result.append(expanded + stripped)
        else:
            # Convert expanded spaces → tabs (with possible remainder spaces).
            n_tabs, remainder = divmod(len(expanded), spaces_per_tab)
            new_leading = "\t" * n_tabs + " " * remainder
            result.append(new_leading + stripped)

    return "".join(result)
