# Security Policy: Privileged Tool Approval

This document defines the approval model for agentic tool execution in SLBP. Its goal is to give the agent broad, friction-free access to the files it is clearly meant to work with, while requiring explicit user approval before accessing anything sensitive or outside the expected workspace.

---

## Core Principle

The agent operates in a **current working directory (cwd)**. Access to files and directories is divided into three tiers based on two criteria: whether the path is inside the cwd, and whether git considers it part of the working tree (tracked or explicitly non-ignored).

| Location | Git status | Approval required? |
|---|---|---|
| Outside cwd | — | **Yes, always** |
| Inside cwd | Tracked or untracked & non-ignored | No (auto-approved) |
| Inside cwd | Gitignored | **Yes** |

The rationale: files that git knows about and does not ignore are files the project intentionally exposes. Ignored files (build artifacts, `.env`, secrets, cache dirs) and files from other parts of the filesystem are not part of the project's intended surface area.

---

## The Approval Callback

Rather than a simple boolean `NEEDS_APPROVAL` flag, each tool module exposes a callable:

```python
def needs_approval(args: dict) -> bool:
    ...
```

This function receives the same `args` dict that `execute()` will receive, resolves the relevant path(s), applies the policy above, and returns `True` if user approval is required before the tool runs. Returning `False` means the tool proceeds silently.

For tools that are always safe or always privileged, the callback can be a trivial one-liner. The callback must **not** have side effects.

---

## The Git Inclusion Check

For a resolved absolute path `P` that is inside cwd, the check is:

```
git ls-files --cached --others --exclude-standard -- <P>
```

- `--cached`: lists tracked files (committed or staged)
- `--others --exclude-standard`: lists untracked files that are **not** gitignored

If this command produces any output, `P` is part of the working tree and is **auto-approved**.
If it produces no output, `P` exists on disk but is gitignored → **approval required**.

This command is run fresh on every tool call so that changes to `.gitignore` are always reflected.

**For directories:** `git ls-files` does not emit directory entries. Instead, use:

```
git check-ignore -q -- <dir>
```

- Exit code 0 → the directory itself matches a gitignore rule → **approval required**
- Exit code 1 → directory is not ignored → **auto-approved**

Note: a non-ignored directory may still contain ignored files. Directory-listing tools (`list_dir`, `search_by_regex`) do not individually screen every file they enumerate — only the root target path is checked. File-reading tools (`read_text_file`, `count_text_file_lines`) check the individual file.

---

## Tool-by-Tool Policy

### `read_text_file`
Reads the contents of a file.

```
needs_approval:
  - Resolve filepath to absolute path.
  - If outside cwd → True.
  - If inside cwd → run git ls-files check on the file → True if ignored, False otherwise.
```

### `count_text_file_lines`
Reads bytes of a file (line counting).

```
needs_approval: same logic as read_text_file.
```

### `list_dir`
Lists directory contents (optionally recursive).

```
needs_approval:
  - Resolve path to absolute path (defaults to cwd itself).
  - If outside cwd → True.
  - If inside cwd → run git check-ignore on the directory → True if ignored, False otherwise.
  - Special case: cwd itself is never ignored (False).
```

### `list_working_tree`
Runs `git ls-files --cached --others --exclude-standard`. This command already filters to non-ignored files by definition.

```
needs_approval:
  - No path arg → always auto-approved (operates on cwd, output is git-filtered).
  - Path arg provided → resolve to absolute.
    - If outside cwd → True.
    - If inside cwd → auto-approved (git ls-files filters the output anyway).
    Note: pointing this tool at an outside-cwd path is treated as privileged even
    though the output would be git-filtered, because the path target itself reveals
    information about the external directory structure.
```

### `search_by_regex`
Searches file contents recursively via ripgrep. Ripgrep is `.gitignore`-aware, but we do not rely on that for the approval decision.

```
needs_approval:
  - Resolve path to absolute (defaults to cwd).
  - If outside cwd → True.
  - If inside cwd → run git check-ignore on the root path.
    - If the root path is a file → run git ls-files check (same as read_text_file).
    - If the root path is a directory → run git check-ignore on the directory.
    - True if ignored, False otherwise.
```

---

## Future Write/Mutate Tools

Any tool that modifies the filesystem (create directory, write file, delete file, rename, etc.) is **always privileged** regardless of path. These tools will have:

```python
def needs_approval(args: dict) -> bool:
    return True
```

No git or path checks are needed — mutation always requires approval.

---

## Approval Workflow (Runtime Behaviour)

When `needs_approval(args)` returns `True`:

1. The agentic loop pauses before `execute()` is called.
2. An `approval_request` socket event is emitted to the UI with the tool name and arguments.
3. The UI displays the request in the approvals column. The user clicks **Approve** or **Deny**.
4. The loop unblocks with the user's decision.
   - **Approved:** `execute()` runs normally.
   - **Denied:** a denial message is injected into message history and the LLM is re-prompted with only `report_impossible` available, forcing it to call that tool.

Only one approval can be pending at a time, because the loop is fully paused while waiting.

---

## Out of Scope

- **Authentication / multi-user isolation:** all socket connections are treated as the same user. This is a single-user local tool.
- **Process execution:** no shell/subprocess execution tools exist yet. When added, they will always require approval.
- **Network requests:** `basic_web_request` and `brave_web_search` are currently not gated (outbound-only, no local state mutation). This may be revisited.
