from __future__ import annotations

ALLOW_REQUEST_UNREDACTED = True

from src.tools._eol import EOL_CHOICES
from src.tools._indentation import (
    INDENT_TARGET_CHOICES,
    DEFAULT_SPACES_PER_TAB,
)
from src.tools._memory import ensure_session_memory
from src.tools._text_editor_actions import _READ_ONLY_ACTIONS, _WRITE_ACTIONS
from src.tools._path_utils import _resolve_path

DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "text_editor",
        "description": (
            "Structural text-editor operations on a session memory string value OR directly on a file on disk. "
            "Provide exactly one of: 'key' (session memory key) or 'filepath' (path to a file on disk). "
            "When 'filepath' is given the file is read into a temporary buffer, the operation is applied, "
            "and (for write actions) the result is written back atomically. "
            "\n\n"
            "LINE ENDING RULES:\n"
            "Only LF (\\n) and CRLF (\\r\\n) are recognised as line terminators. "
            "Bare \\r is treated as a regular character and is never split on or converted. "
            "Write actions always re-encode the result to match the existing EOL style "
            "(CRLF if any CRLF present, else LF). "
            "\n\n"
            "Actions: read_lines, search_by_regex, count_lines, "
            "check_eol, normalize_eol, check_indentation, convert_indentation, apply_patch, "
            "search_replace, regex_replace, insert_lines, delete_lines, append_lines, prepend_lines."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "read_lines",
                        "search_by_regex",
                        "count_lines",
                        "check_eol",
                        "normalize_eol",
                        "check_indentation",
                        "convert_indentation",
                        "apply_patch",
                        "search_replace",
                        "regex_replace",
                        "insert_lines",
                        "delete_lines",
                        "append_lines",
                        "prepend_lines",
                    ],
                    "description": (
                        "The operation to perform:\n"
                        "  read_lines          -- read all or a line range (1-based inclusive).\n"
                        "  search_by_regex     -- search for lines matching a regex; returns matching lines with line numbers.\n"
                        "  count_lines         -- count total lines.\n"
                        "  check_eol           -- report line-ending style statistics.\n"
                        "  normalize_eol       -- normalize all line endings to a single style.\n"
                        "  check_indentation   -- report indentation style statistics.\n"
                        "  convert_indentation -- convert leading-whitespace indentation style.\n"
                        "  apply_patch         -- apply a unified diff patch string ('patch' param). "
                        "Hunks locate themselves by content search; @@ line numbers are used only "
                        "for pure-insertion anchoring. Always matches the target file's EOL style.\n"
                        "  search_replace      -- apply one or more AIDER-style SEARCH/REPLACE blocks "
                        "('patch' param). Skips hunk-header parsing: each block's SEARCH text is located "
                        "by the same fuzzy, single-location, line-count-preserving matching as apply_patch, "
                        "then replaced with the REPLACE text. Each block must match exactly one location; "
                        "use regex_replace to change many locations at once.\n"
                        "  regex_replace       -- replace ALL (or 'count') matches of a Python regex "
                        "('pattern') with 'replacement' (supports \\1 backreferences). Applied with "
                        "re.MULTILINE over the whole content.\n"
                        "  insert_lines        -- insert 'content' before line 'start_line' (1-based).\n"
                        "  delete_lines        -- delete lines 'start_line'..'end_line' (1-based inclusive; "
                        "end_line defaults to start_line).\n"
                        "  append_lines        -- append 'content' to the end.\n"
                        "  prepend_lines       -- prepend 'content' to the beginning."
                    ),
                },
                "key": {
                    "type": "string",
                    "description": (
                        "Session memory key. Must hold a text value. "
                        "Mutually exclusive with 'filepath'. Provide exactly one."
                    ),
                },
                "filepath": {
                    "type": "string",
                    "description": (
                        "Path to a file on disk (relative or absolute). "
                        "The file is read, the operation is applied, and (for write actions) the result is written back. "
                        "Mutually exclusive with 'key'. Provide exactly one."
                    ),
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "1-based start line (inclusive). Used by: read_lines, delete_lines; "
                        "for insert_lines it is the line before which 'content' is inserted "
                        "(1..count+1)."
                    ),
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "1-based end line (inclusive). Used by: read_lines, delete_lines "
                        "(defaults to start_line when omitted)."
                    ),
                },
                "number_lines": {
                    "type": "boolean",
                    "description": "If true, prefix each returned line with its line number. Used by: read_lines.",
                },
                "delimiter": {
                    "type": "string",
                    "description": (
                        "Separator between line number and content when number_lines is true. "
                        "Defaults to ' | '. Used by: read_lines."
                    ),
                },
                "eol": {
                    "type": "string",
                    "enum": EOL_CHOICES,
                    "description": (
                        "Target line-ending style: 'lf' (\\n), 'crlf' (\\r\\n), or 'cr' (\\r). "
                        "Used by: normalize_eol."
                    ),
                },
                "to": {
                    "type": "string",
                    "enum": INDENT_TARGET_CHOICES,
                    "description": "Target indentation style: 'tabs' or 'spaces'. Used by: convert_indentation.",
                },
                "spaces_per_tab": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        f"Number of spaces per tab stop (used in both directions). "
                        f"Default: {DEFAULT_SPACES_PER_TAB}. Used by: convert_indentation."
                    ),
                },
                "pattern": {
                    "type": "string",
                    "description": (
                        "Python regular expression. Used by: search_by_regex (line search) and "
                        "regex_replace (matched against the whole content with re.MULTILINE)."
                    ),
                },
                "patch": {
                    "type": "string",
                    "description": (
                        "For apply_patch: a unidiff/git-diff style patch. "
                        "For search_replace: one or more AIDER-style blocks of the form "
                        "'<<<<<<< SEARCH' / old lines / '=======' / new lines / '>>>>>>> REPLACE'."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Literal text (one or more lines) to add. "
                        "Used by: insert_lines, append_lines, prepend_lines."
                    ),
                },
                "replacement": {
                    "type": "string",
                    "description": (
                        "Replacement template for regex_replace. Supports backreferences "
                        "(e.g. \\1, \\g<name>). Used by: regex_replace."
                    ),
                },
                "count": {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "Maximum number of replacements (0 = replace all). "
                        "Default 0. Used by: regex_replace."
                    ),
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}

# ---------------------------------------------------------------------------
# Approval gating
# ---------------------------------------------------------------------------


_WRITE_ACTIONS_SET = set(_WRITE_ACTIONS)

# Write actions whose approval requirement is decided by a dry-run: if the
# operation would fail or produce no change, don't prompt (the agent sees the
# tool's own error and self-corrects); only prompt when it would actually write.
_DRYRUN_ACTIONS = {
    "apply_patch",
    "search_replace",
    "regex_replace",
    "insert_lines",
    "delete_lines",
    "append_lines",
    "prepend_lines",
}


def dirty_effects(args: dict, session_data: dict | None = None) -> dict:
    action = args.get("action", "")
    filepath = args.get("filepath")
    key = args.get("key")

    if action in _WRITE_ACTIONS_SET:
        if filepath:
            return {"requires_clean_files": [filepath], "dirties_files": [filepath]}
        if key:
            return {"requires_clean_mem": [key], "dirties_mem": [key]}
        return {}

    return {}


def needs_approval(args: dict) -> bool:
    action = args.get("action", "")
    filepath = args.get("filepath")

    if action in _DRYRUN_ACTIONS:
        if filepath is None:
            return False  # session memory key only — no file write

        from src.tools._approval import needs_path_approval, _resolve

        # Outside approved roots: always require approval regardless of outcome.
        if needs_path_approval(filepath):
            return True

        # Path is in-scope. Dry-run the operation: if it would fail (no matches,
        # bad args) or produce no change, auto-approve so the agent sees the
        # tool's own error without a prompt. Only prompt when it WOULD write.
        #
        # Resolve against the session CWD (held in approval thread-locals), not
        # the server process CWD. A relative filepath would otherwise miss the
        # file here and raise.
        resolved_filepath = _resolve(filepath)

        # Read the target. Benign, expected failures (missing file, no
        # permission) mean the write can't happen, so don't prompt. Any OTHER
        # read failure is unexpected: fail safe and require approval.
        try:
            with open(resolved_filepath, "r", encoding="utf-8", newline="") as fh:
                value = fh.read()
        except (FileNotFoundError, PermissionError):
            return False
        except Exception:
            return True

        # Run the pure transform. A message starting with "Error" or an
        # unchanged value means no write happens — no prompt. Only a real,
        # content-changing result requires approval. Any exception: fail safe.
        try:
            message, new_value = _WRITE_ACTIONS[action](args, value, resolved_filepath)
        except Exception:
            return True
        if message.startswith("Error"):
            return False
        return new_value != value

    if action in _WRITE_ACTIONS_SET:
        # Other write actions (normalize_eol, convert_indentation) on files
        # always require explicit approval.
        return filepath is not None

    # Read-only actions: path-based approval (consistent with read_text_file).
    if filepath is not None:
        from src.tools._approval import needs_path_approval
        return needs_path_approval(filepath)
    return False



# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def execute(args: dict, session_data: dict | None = None, special_resources: dict | None = None) -> str:
    if session_data is None:
        session_data = {}

    sr = special_resources or {}
    session_cwd: str | None = sr.get("session_cwd")
    key = args.get("key")
    raw_filepath = args.get("filepath")
    filepath = _resolve_path(raw_filepath, session_cwd) if raw_filepath else None
    action = args.get("action")

    if key and filepath:
        return "Error: provide exactly one of 'key' or 'filepath', not both."
    if not key and not filepath:
        return "Error: one of 'key' or 'filepath' is required."

    # Load content and set label for display messages.
    if filepath:
        label = filepath
        try:
            with open(filepath, "r", encoding="utf-8", newline="") as fh:
                value = fh.read()
        except FileNotFoundError:
            return f"Error: file not found: {filepath}"
        except PermissionError as e:
            return f"Error: permission denied reading file: {e}"
        except OSError as e:
            return f"Error reading file: {e}"
    else:
        label = key
        memory = ensure_session_memory(session_data)
        value = memory.get(key)
        if not isinstance(value, str):
            return f"Error: key {key!r} does not hold a text value."

    if action in _READ_ONLY_ACTIONS:
        return _READ_ONLY_ACTIONS[action](args, value, label)

    if action in _WRITE_ACTIONS:
        message, new_value = _WRITE_ACTIONS[action](args, value, label)
        if not message.startswith("Error"):
            if filepath:
                try:
                    with open(filepath, "w", encoding="utf-8", newline="") as fh:
                        fh.write(new_value)
                except OSError as e:
                    return f"Error writing file: {e}"
            else:
                memory[key] = new_value
        return message

    return f"Error: unknown action {action!r}."
