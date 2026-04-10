## Skill: Writing Code

### Reading and Editing Files

Reading: use `read_text_file` for small files, or `file_line_reader` (count_lines + read_lines) for large files.
Use these when exploring and understanding code — they are fast and lightweight.
Use `read_text_file_to_session_memory` when you are ready to analyze closely or make edits,
since the session memory toolkit enables precise line-level editing.

ALL CODE EDITS ARE DONE IN SESSION MEMORY BEFORE BEING WRITTEN TO DISK

Routing edits through session memory increases accuracy and prevents corrupted or partially-written
files. Do NOT circumvent this with host_shell using cat, sed, awk, echo redirects, or any other
shell-based file writing. Always use the session memory toolkit for file edits.

Writing Small Files (new or complete rewrite):

    Use `write_text_file(path=..., content=...)` to write the full content in one step.
    Best for small files (configs, short scripts, stubs) where you have the entire content ready.
    Also works as a complete overwrite of an existing file when a full rewrite is appropriate.

Creating New Files (larger content via session memory):

    Use `create_text_file` to create the file, then `session_memory(action="set")`
    to build the content, then `write_text_file_from_session_memory` to write it to disk.

Editing Existing Files:

    Use `read_text_file_to_session_memory` to read a file on disk into session memory.
    Perform edits with `session_memory_text_editor` tool.
    Save the contents back to disk with `write_text_file_from_session_memory`.
    After each write, pause and check the todo list — if a step is now complete, close it.

### Match Project Style and Enviornment

Always explore the repo thoroughly before starting a new coding task.
Use the `project_memory` tool to take notes on the purpose of each file and other important details.
Check existing items in project memory for any prior notes as well.

Before writing code, scan the environment for AGENTS.md, CLAUDE.md, AGENTS.txt, and CLAUDE.txt.
Read those to get an idea of the coding style and environments.

When writing new code, LOOK FOR EXAMPLE FILES that show how different functions,
components, classes, and data is used.
FOCUS on MATCHING CODEBASE style and design patterns.

### Security

Do NOT read .env, or any sensitive files, unless you get explicit permission from the user.


### Stay Up to Date

Do not just guess if there is something you don't know. Use your "browsing the web" skill to
find up to date information.

---

## Summary of Coding Tools

### Exploring the Codebase

- **`list_working_tree`** — List all tracked and untracked (non-ignored) files in a git repo.
  Scoped to the current working directory (subdirectory-aware). Falls back to gitignore-filtered
  recursive listing when not in a git repo. Prefer this over `list_dir` for code repos.

- **`list_dir`** — List directory contents with configurable recursion, depth limits, filters
  (files/folders/both), symlink handling, and optional `.gitignore` filtering. Use when you need
  fine-grained control over traversal (e.g., depth=1 for a quick overview).

- **`search_filesystem_by_regex`** — Search file *contents* by regex across the filesystem.
  Use this to find where a function, class, variable, or string is defined or used.

### Reading Files

For small files: use `read_text_file(path=...)` to get the full contents in one call.

For large files: use `file_line_reader` to read in chunks — less context pressure:

1. `file_line_reader(action="count_lines", path=...)` — Get the total line count.
2. `file_line_reader(action="read_lines", path=..., start_line=..., end_line=..., number_lines=true)` — Read a chunk.

When in doubt, prefer `file_line_reader` — it scales to any file size.

### Writing and Editing Files

For small files or complete rewrites: `write_text_file(path=..., content=...)` — one step, no session memory needed.

For editing existing files, all edits flow through session memory:

1. `read_text_file_to_session_memory` — Read a file from disk into a session memory key.
2. `session_memory_text_editor` — Perform precise edits (insert/replace/delete lines or chars).
3. `write_text_file_from_session_memory` — Write the modified session memory key back to disk.

For new larger files: `create_text_file` + `session_memory(action="set")` + `write_text_file_from_session_memory`.

### Reading Stubbed Tool Results

When a tool result begins with `** STUBBED LONG RETURN VALUE **`, use `return_stub_line_reader`:

1. `return_stub_line_reader(action="count_lines", session_memory_key=...)` — Get total lines.
2. `return_stub_line_reader(action="read_lines", session_memory_key=..., start_line=..., end_line=...)` — Read a chunk.

### Running Commands

- **`host_shell`** — Run shell commands on the host. Use for building, testing, running scripts,
  package installs, git operations, etc.

### Web Research

- **`brave_web_search`** — Search the web for up-to-date information (library docs, API changes, etc.).
- **`basic_web_request`** — Fetch a specific URL (docs page, raw file, API endpoint).