## Skill: Writing Code

### Exploring the Codebase

- **`list_working_tree`** — List all tracked/untracked (non-ignored) files in a git repo. Prefer this over `list_dir` for code repos.
- **`list_dir`** — List directory contents with recursion, depth, and filter controls. Use when you need fine-grained traversal (e.g., `depth=1` for a quick overview).
- **`search_filesystem_by_regex`** — Search file *contents* by regex. Use to find where a function, class, variable, or string is defined or used.

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


### Running Commands

Use **`host_shell`** for building, testing, running scripts, package installs, git operations, and other shell tasks.
Do NOT use it for file writing (cat/sed/awk/echo redirects) — always route file edits through session memory.

### Stay Up to Date

If you don't know something, search the web — see the Browsing the Web skill.
