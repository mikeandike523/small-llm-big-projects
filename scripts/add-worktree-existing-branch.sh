#!/bin/bash

set -euo pipefail

branch_name="$1"

git worktree add "../slbp-worktrees/$branch_name" "$branch_name"

cd "../slbp-worktrees/$branch_name"

pnpm run setup-worktree