## Skill: Writing Code

### Using hierarchical todo lists

It is recommended to use a hierarchical todo list, particularly, by starting with tasks such as
"Explore the Codebase" and "Implement Requested Feature", and then adding subtasks as you explore the codebase, begin working on a feature and more.

Read the state of the todo list frequently using `todo_list(action="list_formatted")` to help stay on track
as you complete tasks and subtasks.

Close each item `todo_list(action="close_item")` immediately when done.
Don't just wait until the very end to close them all.

If remaining open items are genuinely impossible to complete,
call `report_impossible` with a clear reason. The user will likely provide a new message with clarification or
direction, so you can continue working.

### Exploring the Codebase

- **`list_working_tree`** — List all tracked/untracked (non-ignored) files in a git repo. Prefer this over `list_dir` for code repos.
- **`list_dir`** — List directory contents with recursion, depth, and filter controls. Use when you need fine-grained traversal (e.g., `depth=1` for a quick overview).
- **`find_files_by_name`** — Search for files by name pattern (glob or regex) across the tree. Prefer this over `host_shell` with `find` — on some systems (e.g. Git Bash on Windows) the `find` command is not available.
- **`search_filesystem_by_regex`** — Search file *contents* by regex. Use to find where a function, class, variable, or string is defined or used.

### Reading and Editing Files

- **Reading**: use `read_text_file` for small files, or `line_reader` (count_lines + read_lines) for large files.
- **Editing existing content**:

Use the `text_editor` tool with one of several `action` parameters to edit file content.
For example, "insert_lines", "delete_lines", "append_lines", "prepend_lines", "apply_patch", "search_replace" and
"regex_replace".
"apply_patch" is preferred to "search_replace", but you can use "search_replace" if patches fail repeatedly.
Only if all editing methods fail, write the whole file anew as a last resort.

- **Writing new files or complete rewrites**: use `write_text_file(path=..., content=...)`.

Do NOT use `host_shell` with cat, sed, awk, or echo redirects for file writing.

### Match Project Style and Environment

Always explore the repo thoroughly before starting a new coding task. Use session memory to record notes on key files and details.

Before writing code, use `get_environment_info` when OS, shell, or working-directory details matter to the task. Scan the environment for AGENTS.md, CLAUDE.md, AGENTS.txt, and CLAUDE.txt — read those for coding style, build/lint/typecheck commands, framework choices, and constraints. Write key takeaways to session memory.

When writing new code, look for example files that show how different functions, components, classes, and data are used. Focus on matching codebase style and design patterns.

### Clarifying Requirements

Before writing any code, consider whether the request leaves room for interpretation. If it does, state your question clearly as your final response and stop — do not use tools. The user will follow up with an answer and the conversation continues with full context.

Common things worth clarifying:
- Which file, module, or component should change — and which should stay untouched?
- Should existing behavior be preserved, or is a clean rewrite acceptable?
- Are there style, framework, or dependency constraints not visible in the code?
- What counts as "done" — does it need tests, docs, a specific output format?

At key branch points mid-task — where two valid paths exist and the choice has significant consequences — state the question and wait rather than picking arbitrarily.

### Security and Sensitive Operations

Do NOT read .env or any sensitive files without explicit user permission.

When a task touches security, authentication, authorization, credentials, cryptography, or destructive operations (mass deletes, schema changes, permission changes), state your questions as your final response *before* making any changes:

- What is in scope vs. off-limits?
- Should existing mechanisms be modified or extended alongside?
- Are there known constraints (compliance requirements, existing patterns to follow)?

### Scratch Files and Quick Computations

Use `code_interpreter` for small or one-off computations — runs Python in a sandboxed environment. Provide code via `raw_code` (inline string) or `code_session_memory_key`. Pass arguments via `sys_argv` and/or `session_memory_arg_keys`. Output returns directly or can be written to `output_session_memory_key`.

Scripts must be non-interactive — design as one-shot: receive data via argv/memory, produce output via stdout, exit. For stateful programs (games, quizzes, simulations), store state in session memory between calls and pass it in as an argument each turn.

For scratch files that must persist on the host, write to the global workspace (`get_global_workspace_dir`), not inside the active project.

### Running Commands

Always use a dedicated tool instead of **`host_shell`** if one is available. `host_shell` is well-suited for building, linting, typechecking, running tests, package installs, and git operations. Do NOT use it for file writing.

Before running any of these, check session memory for notes from code exploration — particularly about project structure, style, and AGENTS.md.

After a build or test run, check the todo list — close verification steps only when they actually pass.

### Presenting Interactive Programs to the User

Use **`open_in_terminal`** — not `host_shell` — whenever you want the user to see and interact with a program:
- Terminal games, quizzes, TUI apps (curses, rich, prompt_toolkit), interactive data-exploration scripts
- Local dev servers the user needs to visit in a browser (`python -m http.server`, `npm run dev`, `flask run`)
- REPLs and long-running processes where watching live output matters

Use `host_shell` for non-interactive commands (builds, tests, linters, installs, git ops) whose output you need to inspect or act on.

### Stay Up to Date

If you don't know something, search the web using `brave_web_search`, then scrape promising URLs into session memory and use `summarize_memory_item` to extract relevant information. See related skill "Browsing the Web" for the full workflow.
