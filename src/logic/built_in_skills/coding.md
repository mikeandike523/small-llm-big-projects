## Skill: Writing Code

### Editing Files

ALL CODE EDITS ARE DONE IN SESSION MEMORY BEFORE BEING WRITTEN TO DISK

Creating New Files:

    Use `create_text_file` to create a new file.
    Use `session_memory(action="set")` to store the initial content.
    Use `write_text_file_from_session_memory` to write the content to the file on disk.

Editing Existing Files:

    Use `read_text_file_to_session_memory` to read a file on disk.
    Perform edits with `session_memory_text_editor` tool.
    Save the contents back to disk with `write_text_file_from_session_memory`

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

### Reading and Editing Files

All edits flow through session memory:

1. `read_text_file_to_session_memory` — Read a file from disk into a session memory key.
2. `session_memory_text_editor` — Perform precise edits (insert/replace/delete lines or chars).
3. `write_text_file_from_session_memory` — Write the modified session memory key back to disk.

For new files: use `create_text_file` + `session_memory(action="set")` + `write_text_file_from_session_memory`.

### Running Commands

- **`host_shell`** — Run shell commands on the host. Use for building, testing, running scripts,
  package installs, git operations, etc.

### Web Research

- **`brave_web_search`** — Search the web for up-to-date information (library docs, API changes, etc.).
- **`basic_web_request`** — Fetch a specific URL (docs page, raw file, API endpoint).