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

## File Length Goal: 500 Lines Maximum

All source files in this project should be kept under 500 lines. When a file approaches or exceeds this limit, break it up using imports, helper modules, and good modularity — not just by reorganizing within the file. Prefer extracting cohesive groups of functions or classes into sibling files (e.g., `_helpers.py`, `_types.py`) and re-importing them.

To identify files that need attention, run:

```
sourcehelper line-count-report over 500
```

This lists all Git-tracked files exceeding 500 lines. Additional subcommands: `top` (top N by line count), `counts` / `lc` (full sorted list), `max` (single largest file), `total` (total line count), `files` (all tracked files). Use `--source-detect-mode` to control file classification speed (`fastest` / `medium` / `precise`). The tool may not be available inside a sandbox — run it on the host.

## Precise File Editing Strategy

When refactoring requires moving large blocks of code between files (e.g., extracting helpers to a new module):

1. **Write a temporary Python script** (e.g., `_extract_<description>.py` at repo root) that reads the source file by line number, writes the extracted lines to the destination file, and rewrites the source file with those lines removed — all in one run.
2. **Run the script, then delete it.**
3. **Use the Edit tool for finishing touches only** — adding the new import, fixing a reference, etc. Small, targeted changes where writing a few tokens from context is low-risk.

**Why:** The Python script reads bytes directly from disk with no quoting or encoding ambiguity. The Edit tool is like working memory — reliable for small surgical edits, but not for reconstructing large blocks from memory (which introduces drift). Never use the Write tool to recreate extracted code from memory.

