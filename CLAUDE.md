# CLAUDE.md -- Environment and Development Tips for this Project

## Project Overview

This project is called "small-llm-big-projects" or "slbp" for short.
The goal is to create an agentic loop that is compatible with smaller models
and avoids the need for massive 100 or more billion parameter models.

The project uses easy-to-use session and project memory tools to bolster an
agent's decision making, making smaller models more viable.

## Project Structure

The repository has four main application areas:

- **`src/`** -- the Python CLI, agent/session orchestration, Flask-SocketIO
  backend, tool implementations, terminal/PTY support, and shared utilities.
  `main.py` registers the CLI routes and the root `slbp`/`slbp.cmd` launchers
  activate the project virtualenv before invoking it.
- **`ui/`** -- the React/Vite browser UI. It contains the dashboard, session
  chat, configuration pages, and browser terminal UI. Production assets are
  built into `ui/dist/` and served by `ui/serve.cjs`.
- **`desktop/`** -- the Electron Forge desktop shell. Its base renderer is
  vanilla TypeScript/DOM code (not React) and owns the custom title bar,
  Health page, changelog dialog, and Process Doctor xterm dialog. Session and
  dashboard tabs are separate `WebContentsView`s that load the React UI from
  the running SLBP proxy. Main-process lifecycle code, preload IPC bridges,
  shared log state, packaging configuration, and desktop scripts all live
  here. Packaged builds are written beneath `desktop/out/`.
- **`server/`** -- local infrastructure and database operations: Docker Compose
  for MySQL, Redis, Piston, and phpMyAdmin; versioned SQL migrations; database
  helpers; and Piston runtime/package setup.

Other important areas are `tests/` for architecture/general pytest coverage,
`tool_tests/` for end-to-end tool testing, `scripts/` for repository-level
maintenance, and the three release-note trees (`backend-release-notes/`,
`ui/public/ui-release-notes/`, and `desktop/desktop-release-notes/`).

Two central runtime commands are `slbp server run`, which starts the agentic
session orchestration stack, and `slbp session new`, which starts a new agent
session and opens its UI. `slbp process-doctor` is the manual recovery tool for
finding and cleaning up orphaned server-stack processes.

## Development Tips

- Before each new feature, review your recent memory files to know what is going on in the project at this time
- Prefer to take more memory notes rather than less. It's good to keep track of what is going on.

## Release Manager

Run the release manager from the repository root through pnpm:

```bash
pnpm run release-manager bump <ui|backend|desktop> <major|minor|patch> <message...>
pnpm run release-manager set <ui|backend|desktop> <X.Y.Z> <message...>
```

Examples:

```bash
pnpm run release-manager bump ui patch "Fix terminal reconnect handling"
pnpm run release-manager bump desktop minor "Add the Process Doctor dialog"
pnpm run release-manager set backend 2.0.0 "New server protocol" --dry-run
```

Use `--dry-run` to preview either operation. `set` normally requires a version
greater than the current version; its `--force` flag permits an equal or lower
version, but it still refuses to overwrite an existing release-note file.

Each invocation changes exactly one target's `package.json`, writes that
target's `<version>.txt` release note, and rebuilds that target's
`changelog-index.json`. Targets have independent versions, so one product
release may reasonably involve one, two, or three separate release-manager
invocations. Conversely, a version bump does not have to map one-to-one to a
Git commit.

The release manager deliberately does **not** run `git add`, create a commit or
tag, push anything, package an application, or deploy. Review the generated
diff, choose how to group release bumps into commits, and commit/push through
the normal Git workflow separately.

## Useful Commands and Scripts

Run commands from the directory shown unless the command explicitly changes
directories itself. Use `pnpm add <package>` in the relevant package directory
when adding JavaScript dependencies; do not hand-edit dependency entries.

### Repository root (`./`)

```bash
./slbp --help                              # CLI command overview
./slbp server run                         # start the backend/UI/proxy stack
./slbp session new                        # create and open a session
./slbp process-doctor                     # interactive orphan-process cleanup
./slbp process-doctor --force-kill-all    # non-interactive cleanup
pnpm run release-manager ...              # version + release-note management
pnpm run ui:type-check                    # TypeScript-check the React UI
pnpm run src:syntax-and-import-check      # parse Python and validate imports
pnpm run format                           # Black for Python + Prettier for UI
pnpm run python:check-unused-imports      # report unused Python imports
pnpm run python:remove-unused-imports     # remove unused Python imports
pnpm run line-counts-over-500             # enforce the source-file size goal
pnpm run db-first-time-setup              # run all structure/seed SQL files
pnpm run update-prod                      # update deps/build/migrations/Piston/systemd
```

`python_in_env.sh` is the standard way to run a Python command in the project
virtualenv from Git Bash, for example `bash python_in_env.sh -m pytest ...`.
`scripts/check_py.py`, `scripts/format.sh`, `scripts/db-first-time-setup.sh`,
and `scripts/update-prod.sh` back the pnpm commands above. `update-prod` is a
deployment-oriented script: it installs dependencies, builds the UI, migrates
the database, configures Piston, and restarts the `slbp` systemd service.

### Browser UI (`./ui`)

```bash
pnpm run vite       # Vite development server
pnpm run build      # TypeScript check plus production Vite build
pnpm run preview    # preview the production build
pnpm run format     # Prettier over the UI tree
node serve.cjs      # serve built UI assets (normally started by SLBP)
```

### Desktop app (`./desktop`)

```bash
pnpm start               # Electron Forge development mode
pnpm run lint            # lint desktop TypeScript
pnpm exec tsc --noEmit   # TypeScript check without emitting files
pnpm run build-icons     # regenerate ico/icns/png from assets/logo.svg
pnpm run close-desktop   # gracefully close this repo's app, then force stragglers
pnpm run package         # clean processes, build icons, package to desktop/out/
pnpm run make            # run configured Electron Forge makers (currently none)
pnpm run publish         # Electron Forge publish workflow
```

`pnpm run package` intentionally runs `slbp process-doctor --force-kill-all`
and `scripts/close-desktop.mjs` first. Packaging therefore stops the running
SLBP server stack and closes desktop instances before replacing build output.
`scripts/prepare-package.mjs` owns that pre-package sequence.

### Infrastructure (`./server`)

```bash
docker compose up -d                    # start MySQL, Redis, Piston, phpMyAdmin
docker compose down                     # stop the local infrastructure
bash migration-runner.sh show           # current and available DB versions
bash migration-runner.sh up             # apply pending migrations
bash migration-runner.sh force-set-version S V
bash run_sql.sh -f path/to/file.sql      # execute an SQL file
bash run_sql.sh -c "SELECT 1"            # execute inline SQL
bash run_sql.sh -m path/to/migrations    # execute all SQL files in a directory
bash reset_db.sh -n                      # dry-run destructive DB reset
bash reset_db.sh                         # confirmed DB reset
bash setup_piston.sh                     # install configured Piston runtime/packages
```

The database scripts read `MYSQL_DATABASE`, `MYSQL_USER`, and
`MYSQL_PASSWORD`, with local defaults documented in their `--help` output.
Use `--help` on `migration-runner.sh`, `run_sql.sh`, or `reset_db.sh` before
unfamiliar or destructive operations.

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

## Logging: Two Separate Mechanisms

### 1. Backend Process Logs — Python `logging` (server diagnostics)

For the human *running the server* — startup info, errors, warnings, general server health.

Configured in `src/ui_connector/main.py` with `logging.basicConfig(force=True)` (overrides Flask). Used via `logging.getLogger(__name__)` across ~15 modules.

- **Desktop app:** stdout/stderr goes to `.slbp-server.log`, tailed by a `LogHistory` ring buffer (`desktop/src/shared/logHistory.ts`, max 500 lines) for the Electron Health tab.
- **Server / systemd:** Captured naturally by the journal.

### 2. Debug Panel Logs — `_emit_backend_log()` (session debug text)

For a *user watching a live session* — real-time colored text about what the agent is doing.

One function in `src/ui_connector/socket_handler_components/emit.py:47-51`. Emits a Socket.IO `backend_log` event per-session. Also written to Redis Streams but excluded from replay.

**Injection points:** `emit_backend_log` is placed in `special_resources` during tool execution (`tool_execution.py:74`) and startup calls (`socket_events.py:226`). Tools like `host_shell.py` and `_managed_process.py` receive it as a parameter.

**Frontend:** `BackendLogsTab.tsx` renders in the Debug Panel via `ansi-to-react`. `useSocketWiring.ts` accumulates up to 100 entries per session.
