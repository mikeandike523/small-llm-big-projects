#!/bin/bash
#
# Safely remove a git worktree (Windows / Git Bash).
#
# Usage: pnpm run remove-worktree <branch-name> [--force]
#
#   0. Refuses if git does not recognize the folder as a valid worktree (e.g.
#      its .git file is missing), since nothing below could be checked then.
#      --force deletes anyway, skipping steps 1 and 2.
#   1. Refuses if the worktree has staged or unstaged changes to tracked files
#      (--force skips this check). Untracked files only produce a warning.
#   2. Warns (yellow, stderr) if the branch is missing on origin or has commits
#      that origin does not have. This never blocks removal.
#   3. Deletes the folder with `byenow` (multi-threaded, single-line progress;
#      https://iobureau.com/byenow) if it is on PATH, otherwise with native
#      `rmdir /s /q`. Both are much faster than `git worktree remove` on
#      node_modules/.venv-heavy trees. Then runs `git worktree prune`.
#
# The branch itself is NOT deleted; only the worktree folder.

set -euo pipefail

YELLOW=$'\033[33m'
RED=$'\033[31m'
GREEN=$'\033[32m'
RESET=$'\033[0m'

warn() { printf '%sWARNING: %s%s\n' "$YELLOW" "$*" "$RESET" >&2; }
die() { printf '%sERROR: %s%s\n' "$RED" "$*" "$RESET" >&2; exit 1; }
info() { printf '%s\n' "$*"; }

usage() {
    echo "Usage: pnpm run remove-worktree <branch-name> [--force]" >&2
    exit 2
}

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
branch_name=""
force=0
for arg in "$@"; do
    case "$arg" in
        --force) force=1 ;;
        -h|--help) usage ;;
        -*) die "Unknown option: $arg" ;;
        *)
            [[ -z "$branch_name" ]] || die "Only one branch name may be given."
            branch_name="$arg"
            ;;
    esac
done
[[ -n "$branch_name" ]] || usage

# ---------------------------------------------------------------------------
# Locate the main worktree and the target worktree (by branch, not by guessing
# the folder path).
# ---------------------------------------------------------------------------
script_dir="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
main_worktree="$(git -C "$script_dir" worktree list --porcelain | sed -n '1s/^worktree //p')"
[[ -n "$main_worktree" ]] || die "Could not determine the main worktree."

# Prints the path of the worktree that has refs/heads/<branch> checked out.
find_worktree_path() {
    local branch="$1" path="" line
    while IFS= read -r line; do
        case "$line" in
            "worktree "*) path="${line#worktree }" ;;
            "branch refs/heads/$branch")
                printf '%s\n' "$path"
                return 0
                ;;
        esac
    done < <(git -C "$main_worktree" worktree list --porcelain)
    return 1
}

wt_path="$(find_worktree_path "$branch_name")" \
    || die "No worktree has branch '$branch_name' checked out. See: git worktree list"

# Compare normalized (unix-style, lowercase) paths so C:/ vs /c/ doesn't matter.
norm() { cygpath -u "$1" | tr '[:upper:]' '[:lower:]' | sed 's:/*$::'; }

[[ "$(norm "$wt_path")" != "$(norm "$main_worktree")" ]] \
    || die "Refusing to remove the main worktree."
[[ -d "$wt_path" ]] || die "Worktree folder does not exist: $wt_path (try: git worktree prune)"

# A shell sitting inside the folder holds a lock on it and makes rmdir fail
# halfway. pnpm passes the caller's original cwd in INIT_CWD.
for cwd in "${INIT_CWD:-}" "$PWD"; do
    [[ -n "$cwd" ]] || continue
    case "$(norm "$cwd")/" in
        "$(norm "$wt_path")"/*) die "Your shell is inside the worktree ($cwd). cd out of it first." ;;
    esac
done

info "Worktree: $wt_path"
info "Branch:   $branch_name"

# The safety checks below only mean something if git recognizes the folder as
# this worktree. Outside a repo, `git diff` silently falls into --no-index mode
# and every check would come back empty, i.e. "looks clean".
wt_toplevel="$(git -C "$wt_path" rev-parse --show-toplevel 2>/dev/null)" || wt_toplevel=""
if [[ -z "$wt_toplevel" || "$(norm "$wt_toplevel")" != "$(norm "$wt_path")" ]]; then
    if [[ $force -eq 1 ]]; then
        warn "Git does not recognize '$wt_path' as a valid worktree (missing/broken .git file?)."
        warn "--force given: deleting WITHOUT checking for uncommitted or unpushed work."
        skip_checks=1
    else
        die "Git does not recognize '$wt_path' as a valid worktree (missing/broken .git file?), so uncommitted work cannot be checked. Inspect it manually, then re-run with --force to delete anyway."
    fi
else
    skip_checks=0
fi

# ---------------------------------------------------------------------------
# 1. Local changes check (blocking unless --force)
# ---------------------------------------------------------------------------
# NOTE: this function is called from an `if` condition, where bash disables
# `set -e`. Every git call therefore needs an explicit `|| die`.
check_local_changes() {
    local staged unstaged untracked
    staged="$(git -C "$wt_path" diff --cached --name-only)" \
        || die "Could not list staged changes (git diff --cached failed)."
    unstaged="$(git -C "$wt_path" diff --name-only)" \
        || die "Could not list unstaged changes (git diff failed)."
    untracked="$(git -C "$wt_path" ls-files --others --exclude-standard)" \
        || die "Could not list untracked files (git ls-files failed)."

    if [[ -n "$untracked" ]]; then
        warn "Untracked (non-ignored) files will be deleted:"
        printf '%s\n' "$untracked" | sed 's/^/    /' >&2
    fi

    if [[ -n "$staged" || -n "$unstaged" ]]; then
        [[ -z "$staged" ]] || { echo "Staged but uncommitted:" >&2; printf '%s\n' "$staged" | sed 's/^/    /' >&2; }
        [[ -z "$unstaged" ]] || { echo "Unstaged changes:" >&2; printf '%s\n' "$unstaged" | sed 's/^/    /' >&2; }
        return 1
    fi
    return 0
}

if [[ $skip_checks -eq 0 ]] && ! check_local_changes; then
    if [[ $force -eq 1 ]]; then
        warn "--force given: discarding the uncommitted changes listed above."
    else
        die "Worktree has uncommitted changes. Commit/stash them, or re-run with --force."
    fi
fi

# ---------------------------------------------------------------------------
# 2. Pushed-to-origin check (warning only)
# ---------------------------------------------------------------------------
check_pushed_to_origin() {
    local branch="$1" remote_sha ls_out ahead

    if ! git -C "$wt_path" remote get-url origin >/dev/null 2>&1; then
        warn "No 'origin' remote configured; cannot check whether '$branch' was pushed."
        return 0
    fi

    # ls-remote asks origin directly, so a stale local origin/<branch> ref
    # can't fool us. Exit code 2 = reachable but ref not found.
    local rc=0
    ls_out="$(git -C "$wt_path" ls-remote --exit-code --heads origin "refs/heads/$branch" 2>/dev/null)" || rc=$?
    if [[ $rc -eq 2 ]]; then
        warn "Branch '$branch' does not exist on origin (never pushed)."
        return 0
    elif [[ $rc -ne 0 ]]; then
        warn "Could not reach origin (git ls-remote exit $rc); push status unknown."
        return 0
    fi
    remote_sha="${ls_out%%[[:space:]]*}"

    # If origin has commits we haven't fetched, fetch them so we can compare.
    if ! git -C "$wt_path" cat-file -e "${remote_sha}^{commit}" 2>/dev/null; then
        if ! git -C "$wt_path" fetch --quiet origin "refs/heads/$branch" 2>/dev/null; then
            warn "Could not fetch origin/$branch; push status unknown."
            return 0
        fi
    fi

    if ! ahead="$(git -C "$wt_path" rev-list --count "$remote_sha..HEAD")"; then
        warn "Could not compare HEAD with origin/$branch; push status unknown."
        return 0
    fi
    if [[ "$ahead" -gt 0 ]]; then
        warn "Branch '$branch' has $ahead commit(s) not pushed to origin:"
        git -C "$wt_path" log --oneline "$remote_sha..HEAD" | sed 's/^/    /' >&2
    fi
}

[[ $skip_checks -eq 1 ]] || check_pushed_to_origin "$branch_name"

# ---------------------------------------------------------------------------
# 3. Delete the folder natively, then prune git's worktree metadata.
# ---------------------------------------------------------------------------
win_path="$(cygpath -w "$wt_path")"
info "Deleting $win_path ..."

# cd somewhere safe so this process doesn't hold a handle on the folder.
cd "$main_worktree"

# Exit codes of both deleters are not trusted; the result is verified below.
if command -v byenow >/dev/null 2>&1; then
    # -y: no confirmation prompt, -1: single-line progress,
    # -b: show byte counts, -e: list files that could not be deleted.
    # -x: byenow refuses anything under C:\Users\ as "restricted" without it;
    #     safe here because wt_path was verified above to be a registered,
    #     non-main worktree.
    byenow -y -x -1 -b -e "$win_path" || true
else
    warn "byenow not found on PATH; falling back to 'rmdir /s /q' (no progress display)."
    # MSYS_NO_PATHCONV stops Git Bash from rewriting /c /s /q into paths.
    MSYS_NO_PATHCONV=1 cmd /c rmdir /s /q "$win_path" || true
fi

if [[ -e "$wt_path" ]]; then
    die "Folder still exists (a file is probably locked by an editor, terminal, or running process). Close it and re-run."
fi

git worktree prune
printf '%sRemoved worktree for %s.%s Branch was kept (delete with: git branch -d %s)\n' \
    "$GREEN" "$branch_name" "$RESET" "$branch_name"
