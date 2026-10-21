# File Access Approval & Gitignore Policy

How the file-reading, listing, and search tools decide (A) whether a call needs
user approval and (B) which files they leave out of their output. These are two
separate concerns: **approval is about permission, output filtering is about
noise.** Keep them apart when changing either.

## Approval modes (all tools)

| Mode | Effect on these tools |
|---|---|
| `full-auto` | Never ask. |
| `auto-accept-edits` | Write tools use the path check below instead of always asking. Read/list/search tools behave exactly as in `default`. |
| `default` | Write tools always ask (`text_editor` first does a dry run and asks only if the write would change the file). Read/list/search tools use the path check below. |

`request_unredacted=True` always asks, in every mode. This is enforced centrally
in `check_needs_approval` (`src/tools/__init__.py`), before the tool's own check.

## The shared path check: `needs_path_approval` (`src/tools/_approval.py`)

Used by `read_text_file`, `line_reader`, `list_dir`, `search_filesystem_by_regex`,
`snapshot_file`, `text_editor` (read actions and dry-run gate), `change_pwd`, and
the write tools in `auto-accept-edits` mode (`write_text_file`, `create_text_file`,
`create_dir`, `delete_file`, `remove_dir`, `copy_file`, `copy_dir`,
`move_dir_or_file`, `restore_file`).

In order:

1. **No path** → no approval.
2. **Resolve:** relative paths are joined to the session's current CWD (falling
   back to its initial CWD), then `Path.resolve()` follows symlinks and `..`. A
   symlink or `../` that leads outside is therefore caught. The server process
   CWD is never used; if no session CWD is set, it raises.
3. **Outside both the initial and current CWD** → ask.
4. **The CWD directory itself** → approved.
5. **The `.git` entry itself, or anything inside `.git/`** → ask. Git does not
   report its own metadata as ignored, so this needs an explicit rule.
6. **Find the repo:** start at the target's nearest *existing* directory, then
   walk up to the drive root looking for a `.git` entry (a directory, or a file
   for worktrees/submodules). This Python walk is what decides "not a repo":
   git exits 128 both for "not a repository" and for real failures (dubious
   ownership, missing directory), and its message text is localized.
   - **No `.git` found** → approved. Being under a session CWD is enough.
     `.gitignore` files above a non-repo directory are deliberately **not**
     consulted for approval.
   - **`.git` found** → git decides, run from that nearest existing directory.
     This also handles a repo nested below a non-repo CWD: its own
     `.gitignore` applies.
7. **Git's verdict:**
   - Existing file: `git ls-files --cached --others --exclude-standard`. The
     path is printed → approved. Empty output → ask.
   - Directory or not-yet-existing path: `git check-ignore -q`. Exit 1 (not
     ignored) → approved. Exit 0 (ignored) → ask.
   - Any git error, a timeout (5s), or a missing git executable → ask.

Fixed 2026-10-18 (hotfix-file-read-approval-error):
- Outside a repo, both git commands fail with exit 128. That used to be read as
  "not ignored" for directories and new files (approved) but as "not included"
  for existing files (ask). So `read_text_file file.txt` in
  `~/.slbp/workspace` asked while listing the folder didn't. Now step 6 handles
  the no-repo case explicitly.
- A new path under a *missing* directory (`ignored-dir/new/x.txt`) ran
  `git -C <missing dir>`. That failed with 128, was read as "not ignored", and
  the path was approved. Git now runs from the nearest existing ancestor.
- A git timeout used to raise `ToolTimeoutError` out of the check (the code
  caught `subprocess.TimeoutExpired`, which `run_command` never raises). A
  missing git raised `FileNotFoundError` the same way. Both now ask instead.
- Listing `.git/` was approved because git reports `.git` as not ignored.

Tests: `tests/test_path_approval_git_policy.py`, `tests/test_approval_modes_policy.py`.

## Per-tool summary

| Tool | Approval check (A) | Filters ignored files by default? (B) | Filtering engine | With no repo | Returns |
|---|---|---|---|---|---|
| `read_text_file` | `needs_path_approval` | n/a | — | descendants approved | file contents |
| `line_reader` | `needs_path_approval` (when `path` given) | n/a | — | descendants approved | file contents |
| `list_dir` | `needs_path_approval` | **no** (`use_gitignore` default false) | `gitignore_parser` | `.gitignore` files up to the drive root apply when filtering is on | names |
| `list_working_tree` | `is_path_in_scope` (CWD check only, no gitignore) | yes, always | `git ls-files`; falls back to `list_dir` with `use_gitignore=True` when git exits 128 | fallback's `.gitignore` handling | names |
| `find_files_by_name` | `is_path_in_scope` (CWD check only) | yes (`use_gitignore` default true) | `git ls-files`; falls back to `list_dir`-style traversal | fallback's `.gitignore` handling | names |
| `search_filesystem_by_regex` | `needs_path_approval` on the root, **plus: `use_gitignore=false` on a directory always asks** | yes (`use_gitignore` default true) | ripgrep (`--no-require-git`; off = `--no-ignore --hidden`) | `.gitignore` files still apply | matching **lines of content** |

### Notes on output filtering (B)

- **`gitignore_parser` path** (`_list_dir_utils.py`: `_find_gitignore_root`,
  `_get_ancestor_matchers`): walks up for `.git`. If none is found it starts at
  the **drive root**, so any `.gitignore` in any parent folder applies. It does
  not read `.git/info/exclude` or the global excludes file, and it does not
  hide dotfiles. It skips `.git/` when filtering is on.
- **`git ls-files` path**: real git semantics, including `info/exclude` and the
  global excludes file. `.git/` is never listed.
- **ripgrep path**: also reads `.ignore` / `.rgignore`, reads parent
  `.gitignore` files, and skips dotfiles unless `use_gitignore=false` (which
  adds `--hidden`).
- These three engines mostly agree but differ at the edges. Unifying them
  (`git ls-files` first, `gitignore_parser` only as a no-repo fallback) is a
  possible later cleanup, not done.

### Why the search rule exists

The search tool's output is file contents. Its root-path approval check can't
vouch for everything under a directory. Without the extra rule,
`search_filesystem_by_regex(pattern=".", use_gitignore=false)` printed every
line of a git-ignored `.env` that `read_text_file` would have asked about.
Redaction still runs on the output, but the gate should match. A single-file
search is fully covered by the normal path check. Directory searches with
ignores off ask even outside a repo, because a nested repo with ignored files
could sit anywhere underneath.

### Deliberately left lenient

`list_working_tree` and `find_files_by_name` only check that the path is under
a session CWD. Listing an ignored folder's *names* there is approved, while
`list_dir` would ask. This was accepted as low risk (names only).
