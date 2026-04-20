from __future__ import annotations

import os
import sys
from pathlib import Path


def get_os() -> str:
    """
    Return a human-readable OS name. Distinguishes Windows, macOS, Linux,
    and Linux-on-WSL. Never misidentifies WSL as plain Windows because WSL
    Python is a Linux binary (sys.platform == 'linux').
    """
    if sys.platform == "win32":
        return "Windows"

    if sys.platform == "darwin":
        return "macOS"

    if sys.platform.startswith("linux"):
        # WSL exposes its distro name in this env var.
        distro = os.environ.get("WSL_DISTRO_NAME", "")
        if distro:
            return f"Linux (WSL: {distro})"

        # Older WSL versions set WSL_INTEROP instead.
        if os.environ.get("WSL_INTEROP"):
            return "Linux (WSL)"

        # Last-resort: inspect the kernel version string.
        try:
            with open("/proc/version") as fh:
                if "microsoft" in fh.read().lower():
                    return "Linux (WSL)"
        except OSError:
            pass

        return "Linux"

    # Fallback for exotic platforms (e.g. FreeBSD, Cygwin …)
    return sys.platform


def get_shell() -> str:
    """
    Return the name of the shell that launched the current process.

    Priority order (most specific first):
      1. Git Bash / MSYS2  – MSYSTEM env var  (MINGW64, MINGW32, UCRT64 …)
      2. PowerShell        – PSModulePath env var
      3. SHELL env var     – covers bash, zsh, fish, sh, dash … on any platform
      4. FISH_VERSION      – fish sets this even when SHELL points elsewhere
      5. Windows cmd       – last resort when os.name == 'nt'
    """
    # Git Bash (runs Windows Python, sets MSYSTEM)
    if os.environ.get("MSYSTEM"):
        return "Git Bash"

    # PowerShell (both Windows PowerShell and pwsh core set PSModulePath)
    if "PSModulePath" in os.environ:
        # Distinguish PowerShell Core (pwsh) from Windows PowerShell
        edition = os.environ.get("PSEdition", "")
        if edition.lower() == "core":
            return "PowerShell (pwsh)"
        return "PowerShell"

    # fish sets FISH_VERSION; it may also set SHELL, but let's be explicit
    if os.environ.get("FISH_VERSION"):
        return "fish"

    # Generic SHELL env var (bash, zsh, sh, fish, dash, …)
    shell_path = os.environ.get("SHELL", "")
    if shell_path:
        name = os.path.basename(shell_path).lower()
        # Strip any trailing version suffix, e.g. "bash-5.1" → "bash"
        name = name.split("-")[0]
        return name

    # Windows cmd fallback
    if os.name == "nt":
        return "cmd"

    return "unknown"


def format_environment_info(
    current_cwd: str | None = None,
    initial_cwd: str | None = None,
) -> str:
    """
    Return a multi-line environment snapshot for prompts and tool output.
    """
    cwd = (current_cwd or os.getcwd()).replace("\\", "/")
    home_dir = str(Path.home()).replace("\\", "/")
    workspace_dir = get_default_workspace_dir()
    lines = [
        f"OS: {get_os()}",
        f"Shell: {get_shell()}",
        f"Current CWD: {cwd}",
        f"User Home Dir: {home_dir}",
        f"Global SLBP Workspace: {workspace_dir}",
    ]
    if initial_cwd:
        initial_cwd_norm = initial_cwd.replace("\\", "/")
        if initial_cwd_norm != cwd:
            lines.append(f"Initial CWD: {initial_cwd_norm}")
    return "\n".join(lines)


def get_default_workspace_dir() -> str:
    """
    Return the app-managed default workspace directory under the user's home directory.
    """
    return str(Path.home() / ".slbp" / "workspace").replace("\\", "/")
