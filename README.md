# Small LLM Big Projects

## Prerequisites

SLBP requires the `rg` (ripgrep) executable for filesystem content searches.
Install ripgrep and make sure `rg` is available on `PATH` before starting the
server:

- Windows: `winget install BurntSushi.ripgrep.MSVC`
- macOS with Homebrew: `brew install ripgrep`
- Ubuntu or Debian: `sudo apt-get install ripgrep`
- Fedora: `sudo dnf install ripgrep`

On Windows, the ripgrep installation directory must be present in either the
user or system `Path` environment variable. Restart SLBP and any open terminals
after changing `Path` so they inherit the new value.

Verify the installation on any platform with:

```text
rg --version
```

The server also requires Docker and, on Windows, Git Bash. See `CLAUDE.md` for
the repository's development and testing commands.
