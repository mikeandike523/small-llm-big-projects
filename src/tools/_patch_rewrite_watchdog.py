from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3

_SYSTEM_PROMPT = (
    "You are a patch repair assistant. "
    "You will be given the full contents of a file and a unified diff patch that "
    "failed to apply to that file. "
    "Your task is to repair the patch so it applies correctly to the file, "
    "while preserving the original intention of the edit.\n\n"
    "Output ONLY the corrected unified diff patch text. "
    "No explanation, no markdown code fences, no commentary."
)


def _dry_run(file_contents: str, patch_text: str) -> bool:
    """Return True if patch_text applies cleanly to file_contents."""
    try:
        from src.tools._text_editor_utils import _parse_patch_file, _apply_edits

        hunks = _parse_patch_file(patch_text)
        if not hunks:
            return False
        _apply_edits(file_contents, hunks)
        return True
    except Exception:
        return False


def attempt_patch_fix(
    file_contents: str,
    original_patch: str,
    on_progress: Callable[[int, int], None],
    max_attempts: int = _MAX_ATTEMPTS,
    patchrewriter_params: dict | None = None,
    on_usage=None,
    on_request_log=None,
    on_reasoning_detected=None,
) -> str | None:
    """Try up to max_attempts LLM calls to produce a version of original_patch
    that applies cleanly to file_contents.

    on_progress(attempt, max_attempts) is called before each LLM call (1-indexed).
    Each attempt sends the same original patch (non-iterative), so the LLM always
    works from the stated intention rather than compounding previous mistakes.
    Returns the first candidate that passes a dry-run, or None if all fail.
    """
    try:
        from src.utils.llm.factory import make_llm, _call_sampler
    except Exception as exc:
        logger.warning("Patch rewrite watchdog: cannot import make_llm: %s", exc)
        return None

    llm = make_llm()
    if llm is None:
        logger.warning("Patch rewrite watchdog: no LLM configured, skipping")
        return None

    params = patchrewriter_params or {}
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"File contents:\n{file_contents}\n\n"
                f"Failed patch:\n{original_patch}"
            ),
        },
    ]

    for attempt in range(1, max_attempts + 1):
        on_progress(attempt, max_attempts)
        try:
            result = _call_sampler(
                llm, messages, params, on_usage,
                on_request_log=on_request_log,
                on_reasoning_detected=on_reasoning_detected,
            )
            candidate = (result.content or "").strip()
            if candidate and _dry_run(file_contents, candidate):
                return candidate
        except Exception as exc:
            logger.warning(
                "Patch rewrite watchdog: attempt %d/%d failed: %s",
                attempt,
                max_attempts,
                exc,
            )

    return None
