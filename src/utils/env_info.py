from __future__ import annotations

import os
import sys


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


def get_env_context() -> str:
    """
    Return a single-line environment note suitable for appending to a user
    message before it is sent to the LLM.

    Example output:
        Note: Current environment — OS: Windows, Shell: Git Bash, CWD: C:/Users/micha/Projects/foo
    """
    cwd = os.getcwd().replace("\\", "/")
    return f"Note: Current environment — OS: {get_os()}, Shell: {get_shell()}, CWD: {cwd}"
