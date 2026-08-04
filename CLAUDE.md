# CLAUDE.md -- Environment and Development Tips for this Project

## project Overview

This project is called "small-llm-big-projects" or "slbp" for short.
The goal is to create an agentic loop that is compatible with smaller models
and avoids the need for massive 100 or more billion parameter models.

The project uses easy-to-use session and project memory tools to bolster
and agent's decision making, making smaller models more viable.

## Project Structure

The project consists of a terminal command and its implementation in `src/**`
as well as a ui, made in react with vite, in `ui/**`

Some of the most important commands are `slbp server run`
hich starts the agentic session orchestration server

and `slbp session new` which starts a new agentic loop session, and opens the ui
in a browser with the new session id

## Development Tips

- Before each new feature, review your recent memory files to know what is going on in the project at this time
- Prefer to take more memory notes rather than less. Its good to keep track of what is going on

## Testing

There are two separate, non-overlapping test suites. Know which one you're touching:

- **`tests/` (pytest)** — general/architecture-level testing: socket handler wiring, CLI arg parsing, skill registry logic, terminal PTY behavior, output truncation, etc. Not tied to any one tool. Run with:
  ```
  bash python_in_env.sh -m pytest -q tests/
  ```
  **Always pass `tests/` explicitly.** There is no `pytest.ini`/`pyproject.toml` configuring `testpaths`, so a bare `pytest` with no path argument walks the whole repo from root — including `server/mysqldata/`, the bind-mounted MySQL Docker data directory. On Windows, `server/mysqldata/mysql.sock` is a Unix-socket symlink that pytest's directory-collection `stat()` call can't handle, raising `OSError: [WinError 1920]` and aborting collection before any real test runs. This is a Windows/pytest quirk, not a project bug — scoping the invocation to `tests/` avoids it entirely.

  `tests/` is populated more ad hoc (by whichever agent/session needed it at the time) and can drift out of date. If a case fails because it references a renamed param or an outdated schema rather than an actual regression, update the test to match current behavior rather than assuming the code is wrong.

- **`tool_tests/` (custom runner)** — tests actual tool *implementations* (the Python functions in `src/tools/`, e.g. `list_dir`, `basic_web_request`, `code_interpreter`). This project doesn't use an MCP server; tools are plain Python modules with a `DEFINITION` schema and a callable, so a generic pytest-style unit test doesn't fit well — `tool_tests/` spins up a real micro HTTP server plus a per-tool sandboxed env and drives each tool end-to-end. Run with:
  ```
  ./tool_tests/run_all.sh
  ./tool_tests/view.sh   # serves the generated test_results/ report in a browser
  ```
  `tool_tests/individual/` is generally kept up to date as tools change, more so than `tests/`.

## File Length Goal: 500 Lines Maximum

All source files in this project should be kept under 500 lines. When a file approaches or exceeds this limit, break it up using imports, helper modules, and good modularity — not just by reorganizing within the file. Prefer extracting cohesive groups of functions or classes into sibling files (e.g., `_helpers.py`, `_types.py`) and re-importing them.

To identify files that need attention, run:

```
sourcehelper line-count-report over 500
```

This lists all Git-tracked files exceeding 500 lines. Additional subcommands: `top` (top N by line count), `counts` / `lc` (full sorted list), `max` (single largest file), `total` (total line count), `files` (all tracked files). Use `--source-detect-mode` to control file classification speed (`fastest` / `medium` / `precise`). The tool may not be available inside a sandbox — run it on the host.

## Precise File Editing Strategy

When refactoring requires moving large blocks of code between files (e.g., extracting helpers to a new module):

1. **Use `sourcehelper range-ops extract-ranges`** to move exact line ranges from a source file into a destination file in one atomic operation.
2. **Use the Edit tool for finishing touches only** — adding the new import, fixing a reference, etc. Small, targeted changes where writing a few tokens from context is low-risk.
3. **Clean up leftover blank lines** with a short Python one-liner rather than context-based edits, e.g. `re.sub(r'\n{3,}', '\n\n', text)` applied to the affected files.

**`extract-ranges` syntax:**

```
sourcehelper range-ops extract-ranges SRC_FILE DST_FILE DST_INSERT_BEFORE_LINE RANGES...
```

- `RANGES` are `START:END` pairs (1-indexed, inclusive), e.g. `10:25 40:60`
- Multiple ranges are extracted in one pass and inserted together at the destination line
- Always run with `--dry` first to confirm the captured lines before committing

**Why:** `extract-ranges` reads and writes bytes directly from disk with no quoting or encoding ambiguity, and removes the extracted lines from the source automatically. The Edit tool is like working memory — reliable for small surgical edits, but not for reconstructing large blocks from memory (which introduces drift). Never use the Write tool to recreate extracted code from memory.

**Explore `sourcehelper` before tackling a hard refactor:** `sourcehelper` is an ever-growing tool with new subcommands added over time. Before starting a difficult refactoring task, run `sourcehelper --help` to see what operations are currently available — there may be a purpose-built command that saves significant manual effort.

