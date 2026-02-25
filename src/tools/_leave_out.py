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
