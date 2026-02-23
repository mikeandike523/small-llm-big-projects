from __future__ import annotations
from typing import List, Optional, Tuple

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "session_memory_apply_patch",
        "description": (
            "Apply a unified diff patch to a session memory text value. "
            "Automatically detects and preserves the original newline style (LF or CRLF). "
            "Allows a small line-offset search (up to 3 lines) so minor line-number "
            "inaccuracies in the patch header do not cause failure. "
            "The patch parameter must be standard unified diff text ONLY — "
            "do NOT wrap it in 'begin patch'/'end patch' markers or any other "
            "surrounding formatting; output only the raw diff. "
            "Part of the in-memory text editor toolkit: "
            "read_text_file_to_session_memory → edit → write_text_file_from_session_memory."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The session memory key. Must hold a text value.",
                },
                "patch": {
                    "type": "string",
                    "description": (
                        "Standard unified diff text (e.g. output of `diff -u`). "
                        "Must start with --- / +++ header lines and contain one or more hunks. "
                        "Do NOT include 'begin patch', 'end patch', or any other wrapper — "
                        "raw diff text only."
                    ),
                },
            },
            "required": ["key", "patch"],
            "additionalProperties": False,
        },
    },
}


def needs_approval(args: dict) -> bool:
    return False


def _detect_newline_style(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _split_lines_preserve(text: str) -> Tuple[List[str], bool]:
    if text == "":
        return [], False
    had_trailing_newline = text.endswith("\n")
    lines = text.splitlines()
    return lines, had_trailing_newline


def _apply_patch(original_text: str, patch_text: str) -> str:
    """Apply a unified diff to an in-memory string with CRLF-awareness and small offset fuzz."""
    try:
        from unidiff import PatchSet
    except ImportError:
        raise RuntimeError(
            "The 'unidiff' package is required for session_memory_apply_patch. "
            "Install it with: pip install unidiff"
        )

    newline = _detect_newline_style(original_text)
    orig_lines, orig_had_final_nl = _split_lines_preserve(original_text)

    # Normalise the patch text: strip CRLF so unidiff parses cleanly
    patch_text_normalized = patch_text.replace("\r\n", "\n").replace("\r", "\n")

    patchset = PatchSet(patch_text_normalized)

    if len(patchset) == 0:
        raise ValueError("Patch contains no file entries.")
    if len(patchset) > 1:
        raise ValueError(
            f"Patch targets {len(patchset)} files; this tool applies patches to a single "
            "session memory value (one file) at a time."
        )

    pfile = patchset[0]
    lines = list(orig_lines)
    max_offset = 3

    for hunk in pfile:
        target_index_0 = max(hunk.source_start - 1, 0)

        expected_before: List[str] = [
            ln.value.rstrip("\n\r")
            for ln in hunk
            if ln.is_context or ln.is_removed
        ]
        expected_after: List[str] = [
            ln.value.rstrip("\n\r")
            for ln in hunk
            if ln.is_context or ln.is_added
        ]

        def matches_at(idx: int) -> bool:
            if idx < 0:
                return False
            if idx + len(expected_before) > len(lines):
                return False
            return lines[idx: idx + len(expected_before)] == expected_before

        apply_at: Optional[int] = None

        if matches_at(target_index_0):
            apply_at = target_index_0
        else:
            lo = max(0, target_index_0 - max_offset)
            hi = min(len(lines), target_index_0 + max_offset + 1)
            hits = [i for i in range(lo, hi) if matches_at(i)]

            if len(hits) == 1:
                apply_at = hits[0]
            elif len(hits) == 0:
                raise ValueError(
                    f"Hunk @@ line {hunk.source_start} did not match anywhere within "
                    f"+/-{max_offset} lines of the stated position."
                )
            else:
                raise ValueError(
                    f"Hunk @@ line {hunk.source_start} matches multiple locations "
                    f"({[h + 1 for h in hits]}); ambiguous, refusing to apply."
                )

        lines = (
            lines[:apply_at]
            + expected_after
            + lines[apply_at + len(expected_before):]
        )

    result = newline.join(lines)
    if orig_had_final_nl:
        result += newline
    return result


def _ensure_session_memory(session_data: dict) -> dict:
    memory = session_data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        session_data["memory"] = memory
    return memory


def execute(args: dict, session_data: dict | None = None) -> str:
    if session_data is None:
        session_data = {}
    memory = _ensure_session_memory(session_data)

    key: str = args["key"]
    patch: str = args["patch"]

    value = memory.get(key)
    if not isinstance(value, str):
        return f"Error: key {key!r} does not hold a text value."

    try:
        result = _apply_patch(value, patch)
    except (ValueError, RuntimeError) as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error applying patch: {exc}"

    memory[key] = result

    original_lines = len(value.splitlines())
    new_lines = len(result.splitlines())
    delta = new_lines - original_lines
    sign = "+" if delta >= 0 else ""
    return (
        f"Patch applied to {key!r}. "
        f"Lines: {original_lines} -> {new_lines} ({sign}{delta})."
    )
