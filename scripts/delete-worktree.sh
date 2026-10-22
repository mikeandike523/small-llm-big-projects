#!/bin/bash

set -euo pipefail

local branch_name="$1"

cmd /c "rmdir /s /q ../slbp-worktrees/$branch_name"

git worktree prune