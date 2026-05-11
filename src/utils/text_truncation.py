from __future__ import annotations


def truncate_long_lines(text: str, max_len: int) -> str:
    """
    Truncate lines in text that exceed max_len visible characters.

    Splits on '\\n' only. Trailing '\\r' on each segment is stripped before
    measuring, excluded from the length count, and restored afterward —
    so both '\\n' and '\\r\\n' line endings round-trip correctly.

    Appends '[... N more bytes]' to any truncated line (mirrors rg --max-columns-preview).
    max_len=0 disables truncation and returns text unchanged.
    """
    if max_len == 0:
        return text
    out = []
    for line in text.split("\n"):
        has_cr = line.endswith("\r")
        content = line[:-1] if has_cr else line
        if len(content) > max_len:
            content = content[:max_len] + f"[... {len(content) - max_len} more bytes]"
        out.append((content + "\r") if has_cr else content)
    return "\n".join(out)
