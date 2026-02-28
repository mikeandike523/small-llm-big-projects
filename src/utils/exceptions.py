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
