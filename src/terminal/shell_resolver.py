from __future__ import annotations

import os
import shutil
import sys

from src.utils.env_info import get_os


class ShellNotFoundError(RuntimeError):
    pass


def _find_git_bash() -> str | None:
    """Locate Git Bash on Windows, preferring 64-bit install."""
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    # PATH fallback — only accept if it looks like Git Bash, not WSL bash.
    found = shutil.which("bash")
    if found:
        found_lower = found.lower()
        if "git" in found_lower and "wsl" not in found_lower:
            return found
    return None


def resolve_shell() -> list[str]:
    """
    Return spawn argv for an interactive login shell on the current platform.

    - Windows  -> Git Bash  (--login -i)
    - macOS    -> zsh or bash (-l -i)
    - Linux    -> $SHELL, then bash (-l -i)

    Raises ShellNotFoundError if no suitable shell can be located.
    """
    os_name = get_os()

    if os_name == "Windows":
        git_bash = _find_git_bash()
        if git_bash is None:
            raise ShellNotFoundError(
                "Git Bash not found. "
                "Install Git for Windows from https://git-scm.com/"
            )
        return [git_bash, "--login", "-i"]

    if os_name == "macOS":
        for shell in ("zsh", "bash"):
            path = shutil.which(shell)
            if path:
                return [path, "-l", "-i"]
        raise ShellNotFoundError("Neither zsh nor bash found on macOS")

    # Linux / WSL — prefer the user's configured shell, fall back to bash.
    user_shell = os.environ.get("SHELL", "")
    if user_shell and os.path.isfile(user_shell):
        return [user_shell, "--login", "-i"]
    bash = shutil.which("bash")
    if bash:
        return [bash, "--login", "-i"]
    raise ShellNotFoundError("No suitable shell found on this Linux system")
