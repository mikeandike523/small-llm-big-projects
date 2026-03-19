class ToolTimeoutError(Exception):
    def __init__(
        self,
        tool_name: str,
        timeout: int | float,
        hint: str | None = None,
        prior_stdout: str | None = None,
        prior_stderr: str | None = None,
    ):
        self.tool_name = tool_name
        self.timeout = timeout
        self.hint = hint
        self.prior_stdout = prior_stdout
        self.prior_stderr = prior_stderr

    def __str__(self) -> str:
        parts = [f"{self.tool_name} timed out ({self.timeout}s)"]
        if self.hint:
            parts.append(f"Hint: {self.hint}")
        if self.prior_stdout:
            parts.append(f"\nPrior shell stdout:\n{self.prior_stdout.rstrip()}")
        if self.prior_stderr:
            parts.append(f"\nPrior shell stderr:\n{self.prior_stderr.rstrip()}")
        return "\n".join(parts)


class ToolHangError(Exception):
    def __init__(
        self,
        tool_name: str,
        hang_timeout: int | float,
        prior_stdout: str | None = None,
        prior_stderr: str | None = None,
    ):
        self.tool_name = tool_name
        self.hang_timeout = hang_timeout
        self.prior_stdout = prior_stdout
        self.prior_stderr = prior_stderr

    def __str__(self) -> str:
        parts = [
            f"{self.tool_name} process was killed after {self.hang_timeout}s of no output. "
            f"See the streaming log for the triage decision details."
        ]
        if self.prior_stdout:
            parts.append(f"\nPrior shell stdout:\n{self.prior_stdout.rstrip()}")
        if self.prior_stderr:
            parts.append(f"\nPrior shell stderr:\n{self.prior_stderr.rstrip()}")
        return "\n".join(parts)
