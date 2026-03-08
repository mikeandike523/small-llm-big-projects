class ToolTimeoutError(Exception):
    def __init__(self, tool_name: str, timeout: int | float, hint: str | None = None):
        self.tool_name = tool_name
        self.timeout = timeout
        self.hint = hint

    def __str__(self) -> str:
        msg = f"{self.tool_name} timed out ({self.timeout}s)"
        if self.hint:
            msg += f"\nHint: {self.hint}"
        return msg


class ToolHangError(Exception):
    def __init__(self, tool_name: str, hang_timeout: int | float):
        self.tool_name = tool_name
        self.hang_timeout = hang_timeout

    def __str__(self) -> str:
        return (
            f"{self.tool_name} process hung: no new output for {self.hang_timeout}s "
            f"and no autoresponder matched. The process is likely waiting for interactive "
            f"input with no applicable autoresponse rule."
        )
