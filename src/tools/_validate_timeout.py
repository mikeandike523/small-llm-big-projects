import math
from typing import Any, Optional
from numbers import Number
from src.utils.tool_calling.arguments import InvalidTypeError, NumberConstraintError


def validate_timeout(
        tool_name: str,
        timeout: Any,
        default_timeout: Number,
        max_timeout: Optional[Number]
):
    if not isinstance(timeout, Number):
        raise InvalidTypeError(
            tool_name,
            "timeout",
            str(Number),
            str(type(timeout))
        )

    if not math.isfinite(timeout):
        raise NumberConstraintError(tool_name,"timeout", "Timeout must be a finite number.", timeout)
    
    if max_timeout is None:
        max_timeout = default_timeout
    
    if not timeout > 0:
        raise NumberConstraintError(tool_name, "timeout", "Timeout must be strictly greater than 0 seconds", timeout)
    
    if timeout > max_timeout:
        raise NumberConstraintError(tool_name,"timeout", f"Timeout cannot be greater than {max_timeout} seconds")
    