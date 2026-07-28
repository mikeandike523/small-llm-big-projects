#!/bin/bash
# Activate the virtualenv and set PYTHONPATH to the repo root, then run
# the given Python script (or any command) with those settings in effect.
#
# Usage:
#   ./python_in_env.sh path/to/script.py [args...]
#   ./python_in_env.sh -m some.module [args...]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ACTIVATE_SCRIPT=""

# Check for Windows virtualenv activation script (Git Bash / MINGW64)
if [[ -f "$REPO_ROOT/.venv/Scripts/activate" ]]; then
    ACTIVATE_SCRIPT="$REPO_ROOT/.venv/Scripts/activate"
# Check for Unix virtualenv activation script
elif [[ -f "$REPO_ROOT/.venv/bin/activate" ]]; then
    ACTIVATE_SCRIPT="$REPO_ROOT/.venv/bin/activate"
fi

if [[ -z "$ACTIVATE_SCRIPT" ]]; then
    echo "Error: Could not find virtualenv activation script." >&2
    echo "Looked for:" >&2
    echo "  - $REPO_ROOT/.venv/Scripts/activate (Windows)" >&2
    echo "  - $REPO_ROOT/.venv/bin/activate (Unix)" >&2
    exit 1
fi

# Source the activation script
source "$ACTIVATE_SCRIPT"

# Prepend repo root to PYTHONPATH so that "from src.xxx" imports work
export PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}"

exec python "$@"
