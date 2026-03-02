from __future__ import annotations

from enum import Enum


class LeaveOut(str, Enum):
    """Controls how a tool's call + result are treated when stripping context for retry."""
    KEEP = "KEEP"
    PARAMS_ONLY = "PARAMS_ONLY"
    OMIT = "OMIT"
    SHORT = "SHORT"


def get_leave_out(module) -> LeaveOut:
    """Return the LEAVE_OUT policy for a tool module, defaulting to KEEP."""
    val = getattr(module, "LEAVE_OUT", LeaveOut.KEEP)
    if isinstance(val, LeaveOut):
        return val
    if isinstance(val, str):
        try:
            return LeaveOut(val)
        except ValueError:
            return LeaveOut.KEEP
    return LeaveOut.KEEP


def get_short_amount(module) -> int:
    """Return the TOOL_SHORT_AMOUNT for a SHORT-policy tool, defaulting to 500."""
    return int(getattr(module, "TOOL_SHORT_AMOUNT", 500))


def get_leave_out_for_args(module, args: dict | None) -> tuple[LeaveOut, int]:
    """Return (policy, short_amount) for a specific tool call.

    Checks LEAVE_OUT_PER_ACTION[action] first; falls back to module-level LEAVE_OUT.
    """
    per_action = getattr(module, "LEAVE_OUT_PER_ACTION", None)
    if per_action is not None and args:
        action = args.get("action")
        if action and action in per_action:
            entry = per_action[action]
            policy_str, short_amt = entry if isinstance(entry, tuple) else (entry, 500)
            try:
                return LeaveOut(policy_str), int(short_amt)
            except ValueError:
                pass
    return get_leave_out(module), get_short_amount(module)
