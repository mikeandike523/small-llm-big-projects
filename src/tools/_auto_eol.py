"""Auto-EOL normalization for newly created files.

Gated by the `system.create_file_auto_eol` param ("enabled" / "enabled_silent" /
"disabled"). The target line-ending style is detected from the session's INITIAL
cwd (not the current cwd), with this precedence:

  1. .gitattributes with an `eol=lf` / `eol=crlf` directive
  2. a *.code-workspace file (JSONC) whose `settings` has `files.eol`
     (either the flat "files.eol" key or nested "files": {"eol": ...})
  3. host platform default: CRLF on Windows (incl. git bash), LF on mac/Linux

The detection is deliberately simple for now; heuristics can be enriched later.
"""
from __future__ import annotations

import glob
import os
import sys

from src.tools._eol import normalize_eol

# Param values that turn the feature on.
_ACTIVE_MODES = ("enabled", "enabled_silent")


def _platform_default_eol() -> str:
    # git bash on Windows still runs Windows Python, so sys.platform == "win32".
    return "crlf" if sys.platform.startswith("win") else "lf"


def _eol_from_gitattributes(init_cwd: str) -> str | None:
    path = os.path.join(init_cwd, ".gitattributes")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                # Collapse internal whitespace so "* text=auto eol=lf" matches
                # regardless of spacing/tabs between attributes.
                low = " ".join(line.lower().split())
                if "eol=lf" in low:
                    return "lf"
                if "eol=crlf" in low:
                    return "crlf"
    except (FileNotFoundError, OSError):
        return None
    return None


def _eol_value_to_style(eol_val: object) -> str | None:
    if eol_val == "\n":
        return "lf"
    if eol_val == "\r\n":
        return "crlf"
    return None


def _eol_from_code_workspace(init_cwd: str) -> str | None:
    try:
        candidates = sorted(glob.glob(os.path.join(init_cwd, "*.code-workspace")))
    except OSError:
        return None
    if not candidates:
        return None

    try:
        import json5  # JSONC superset; handles comments + trailing commas.
    except Exception:
        # Library unavailable — degrade gracefully (fall through to platform default).
        return None

    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                data = json5.loads(fh.read())
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        settings = data.get("settings")
        if not isinstance(settings, dict):
            continue
        # VSCode stores this as the flat dotted key "files.eol"; also accept a
        # nested {"files": {"eol": ...}} shape.
        eol_val = settings.get("files.eol")
        if eol_val is None:
            files = settings.get("files")
            if isinstance(files, dict):
                eol_val = files.get("eol")
        style = _eol_value_to_style(eol_val)
        if style:
            return style
    return None


def detect_target_eol(init_cwd: str | None) -> str:
    """Return the target EOL style ('lf' or 'crlf') for files in init_cwd."""
    if init_cwd:
        for detector in (_eol_from_gitattributes, _eol_from_code_workspace):
            style = detector(init_cwd)
            if style:
                return style
    return _platform_default_eol()


def maybe_apply_auto_eol(
    content: str,
    mode: str | None,
    init_cwd: str | None,
) -> tuple[str, str | None]:
    """Apply auto-EOL normalization to content for a newly created file.

    Returns (possibly_converted_content, note). `note` is a human-readable
    message to append to the tool result, and is non-None ONLY when a conversion
    actually changed the content AND mode == "enabled" (verbose). It is always
    None for "enabled_silent" and "disabled".
    """
    if mode not in _ACTIVE_MODES:
        return content, None
    target = detect_target_eol(init_cwd)
    converted = normalize_eol(content, target)
    if converted == content:
        return content, None
    note = f"Line endings normalized to {target.upper()}." if mode == "enabled" else None
    return converted, note
