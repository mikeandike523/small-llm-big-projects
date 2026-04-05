## Skill: Writing Code and Working in Large Repos

### 1. Orient yourself before writing a single line

At the start of any new coding task, search the repository root for orientation files:
`AGENTS.md`, `AGENTS.txt`, `CLAUDE.md`, `claude.md` (and `.txt` variants).
Read every one you find. These files contain the project's coding conventions, tooling
setup, environment requirements, and security guidelines — ignoring them is the most
common cause of doing work that has to be redone.

Take notes in project memory immediately after reading them. Focus on:
- What language(s), runtime(s), and package managers are in use
- How to run tests, linters, and build steps
- Any non-obvious security rules or constraints
- Any preferred patterns or things to explicitly avoid

### 2. Survey the repository structure early

Before diving into code, get a high-level picture of what is in the repo. In a git
repository, use `list_working_tree` — it respects `.gitignore` and gives a clean view
of all tracked and untracked files. In a non-git directory, use `list_dir` with a small
`depth` (2–3) to avoid noise.

Look for files that reveal the project's toolchain and structure:
- Package manifests: `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `pom.xml`
- Lock files: which exact package manager is in use (`yarn.lock` vs `package-lock.json`, etc.)
- Config files: `tsconfig.json`, `.eslintrc`, `jest.config.*`, `vite.config.*`, `Dockerfile`
- CI definitions: `.github/workflows/`, `.gitlab-ci.yml` — these show exactly how the project is built and tested

Record key findings (root layout, entry points, config file locations) in project memory
so you don't have to re-scan later.

### 3. Consult project memory before each major step

Before starting each significant phase of work (e.g. implementing a feature, refactoring
a module, writing tests), list your project memory keys and read any relevant entries.
You may have noted something earlier in this session or a prior one that saves you from
repeating a failed approach or re-researching something you already know.

### 4. Validate with the actual toolchain — don't assume

Use `host_shell` to run the project's real tools as you go:
- Type-check: `tsc --noEmit`, `mypy`, `pyright`, etc.
- Lint: `eslint`, `ruff`, `flake8`, etc.
- Test: `pytest`, `jest`, `cargo test`, `go test ./...`, etc.
- Build: `npm run build`, `cargo build`, etc.

Read errors carefully. A compile error or import failure often reveals something important
about how the project is structured — which version of a library is actually installed,
which module paths are canonical, which features are enabled. Take a note in project memory
when an error teaches you something non-obvious about the tooling or environment.

Watch for `HANG:` or `TIMEOUT:` results — interactive commands (prompts, REPLs, watchers)
will hang indefinitely. Always pass non-interactive flags (`--no-interactive`, `--yes`, `CI=1`,
etc.) and prefer single-pass commands over long-running watchers.

### 5. Security — handle sensitive files and secrets with care

Do NOT read `.env` files, secret files, private keys, credentials, or any file whose
name or path suggests it contains sensitive data (e.g. `.env`, `.env.local`, `secrets.yaml`,
`credentials.json`, `*.pem`, `*.key`) unless the user has explicitly instructed you to.
These files frequently contain tokens, passwords, and private keys. Even if a task seems
to require it, stop and ask the user rather than reading them on your own initiative.

More broadly:
- Do not log, print, or store secret values in project or session memory
- Do not include real credentials in any code you write — use placeholder names like `YOUR_API_KEY`
- If you encounter a secret incidentally (e.g. in a tool result), do not repeat it back
- Treat `.gitignore` entries as hints about what the project considers sensitive

### 6. Search the web when in doubt about APIs or library versions

Library APIs change. Documentation goes stale. If you are about to write code that
calls a third-party library, framework, or CLI tool — especially one that moves fast or
that you are not certain about — use `brave_web_search` first.

Err heavily on the side of searching more rather than less. The cost of one extra search
is low; the cost of writing code against a deprecated API and then having to unpick it is
high. Always prefer a current source (official docs, a recent changelog, a release note)
over your training knowledge when the two might differ.

Things that are almost always worth a quick search before coding:
- The correct import path or package name for an unfamiliar library
- Whether a specific method or flag still exists in the current version
- The recommended way to do something that may have changed recently
- Any error message you don't immediately recognise

Save useful references (URL, date, key facts) in project memory so you don't re-search
the same thing multiple times in a long task.

### 7. Keep running notes in project memory

After each major step, write a brief summary note to project memory:
what you did, what you found, and any gotchas encountered. Use short, descriptive key names
like `notes.auth-refactor`, `notes.test-setup`, `notes.env-vars`.

Important findings to always record:
- Which commands actually work (and with what flags)
- Non-obvious file locations (config files, entry points, generated files)
- Environment variables or secrets the project needs
- Any workaround you had to apply and why

These notes make every subsequent step faster and protect you from rediscovering the same
information repeatedly across a long task.
