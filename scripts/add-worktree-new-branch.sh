#!/bin/bash

set -euo pipefail

local branch_name="$1"

git worktree add -b "$branch_name" "../slbp-worktrees/$branch_name"

cd "../slbp-worktrees/$branch_name"

pnpm run setup-worktree