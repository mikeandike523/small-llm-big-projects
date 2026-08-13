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


def _wrap_in_login_shell(shell_cmd: str) -> list[str] | str:
    """Wrap *shell_cmd* (a raw shell script/command line) in the platform login
    shell (bash -lc / zsh -lc) so that shell-managed PATH entries (nvm, pyenv,
    etc.), builtins, aliases, and operators (&&, |, etc.) all work.

    Returns list[str] on success, or an error string if the required shell
    cannot be found.
    """
    os_name = get_os()

    if os_name == "Windows":
        git_bash = _find_git_bash()
        if git_bash is None:
            return (
                "Error: Git Bash not found. "
                "Git Bash is a prerequisite of slbp on Windows. "
                "Install from https://git-scm.com/"
            )
        return [git_bash, "-lc", shell_cmd]

    if os_name == "macOS":
        for shell in ("zsh", "bash"):
            path = shutil.which(shell)
            if path:
                return [path, "-lc", shell_cmd]
        return "Error: Neither zsh nor bash found on macOS."

    user_shell = os.environ.get("SHELL", "")
    if user_shell and os.path.isfile(user_shell):
        return [user_shell, "-lc", shell_cmd]
    bash = shutil.which("bash")
    if bash:
        return [bash, "-lc", shell_cmd]
    return "Error: No suitable shell found on this Linux system."


def resolve_cmd(command: str, command_args: list[str]) -> list[str] | str:
    """
    Build the final argv list for *command* + *command_args*.

    If *command* is directly resolvable via shutil.which, run it as-is.
    Otherwise wrap in the platform login shell (bash -lc / zsh -lc) so that
    shell-managed PATH entries (nvm, pyenv, etc.) are available.

    Returns list[str] on success, or an error string if the required shell
    cannot be found.
    """
    import shlex

    # Leniency for weaker models: despite the command/command_args split, they
    # routinely stuff a whole shell line into `command` -- "cd /foo && ls -la",
    # "echo hi | grep h", chained commands, redirects, etc. -- a habit carried
    # over from generic shell-hygiene training rather than this tool's schema.
    # shutil.which() can never resolve a string containing whitespace, so this
    # used to fall into the shlex.join() fallback below, which shlex.quote()'s
    # the *entire* string as a single argv token -- turning a real multi-word
    # command into a broken "command not found". Detect it up front and run it
    # as a raw shell script instead, exactly as the model intended.
    if any(ch.isspace() for ch in command):
        shell_cmd = command if not command_args else command + " " + " ".join(command_args)
        return _wrap_in_login_shell(shell_cmd)

    resolved = shutil.which(command)
    if resolved:
        return [resolved] + command_args

    # `command` is a single token but not directly resolvable via `which` --
    # a shell builtin (cd, source), an alias, or something only visible after
    # shell init (nvm/pyenv-managed PATH). Reassemble with proper quoting and
    # let the login shell resolve it.
    shell_cmd = shlex.join([command] + command_args)
    return _wrap_in_login_shell(shell_cmd)


def resolve_shell_cmd(command_line: str) -> list[str]:
    """
    Wrap *command_line* in the platform shell for non-interactive PTY execution.
    Like resolve_shell() but runs a specific command instead of an interactive REPL.
    """
    os_name = get_os()

    if os_name == "Windows":
        git_bash = _find_git_bash()
        if git_bash is None:
            raise ShellNotFoundError(
                "Git Bash not found. "
                "Install Git for Windows from https://git-scm.com/"
            )
        return [git_bash, "-lc", command_line]

    if os_name == "macOS":
        for shell in ("zsh", "bash"):
            path = shutil.which(shell)
            if path:
                return [path, "-lc", command_line]
        raise ShellNotFoundError("Neither zsh nor bash found on macOS")

    user_shell = os.environ.get("SHELL", "")
    if user_shell and os.path.isfile(user_shell):
        return [user_shell, "-lc", command_line]
    bash = shutil.which("bash")
    if bash:
        return [bash, "-lc", command_line]
    raise ShellNotFoundError("No suitable shell found on this Linux system")


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
