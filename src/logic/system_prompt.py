import os

_BUILT_IN_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "built_in_skills")
_GENERAL_SKILLS_DIR = os.path.join(_BUILT_IN_SKILLS_DIR, "general")
_SPECIALIZED_SKILLS_DIR = os.path.join(_BUILT_IN_SKILLS_DIR, "specialized")


def parse_skill_title(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        if len(stripped) > 50:
            return stripped[:50] + "..."
        return stripped
    return "(untitled)"


def _load_skill_files_from_dir(directory: str, source: str) -> list[dict]:
    entries: list[dict] = []
    try:
        filenames = sorted(f for f in os.listdir(directory) if f.lower().endswith(".md"))
    except OSError:
        return entries
    for filename in filenames:
        path = os.path.join(directory, filename)
        try:
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            title = parse_skill_title(content)
        except OSError:
            title = filename
            content = ""
        entries.append({"title": title, "filename": filename, "path": path, "source": source, "_content": content})
    return entries


def build_skill_registry(custom_skills_path: str | None = None) -> list[dict]:
    """Return a list of skill file descriptors for general, specialized, and custom skills.

    Each entry: {title, filename, path, source}
    source is one of: 'builtin_general', 'builtin_specialized', 'custom_general', 'custom_specialized'

    Custom skill loading rules:
    - Files directly in custom_skills_path root     -> custom_general (backwards compat)
    - Files in custom_skills_path/general/          -> custom_general
    - Files in custom_skills_path/specialized/      -> custom_specialized
    """
    registry: list[dict] = []

    for entry in _load_skill_files_from_dir(_GENERAL_SKILLS_DIR, "builtin_general"):
        registry.append({k: v for k, v in entry.items() if k != "_content"})

    for entry in _load_skill_files_from_dir(_SPECIALIZED_SKILLS_DIR, "builtin_specialized"):
        registry.append({k: v for k, v in entry.items() if k != "_content"})

    if custom_skills_path:
        # Root-level .md files (backwards compat) -> general
        try:
            root_files = sorted(f for f in os.listdir(custom_skills_path) if f.lower().endswith(".md"))
        except OSError:
            root_files = []
        for filename in root_files:
            path = os.path.join(custom_skills_path, filename)
            try:
                with open(path, encoding="utf-8") as fh:
                    content = fh.read()
                title = parse_skill_title(content)
            except OSError:
                title = filename
            registry.append({"title": title, "filename": filename, "path": path, "source": "custom_general"})

        # general/ subfolder -> general
        for entry in _load_skill_files_from_dir(
            os.path.join(custom_skills_path, "general"), "custom_general"
        ):
            registry.append({k: v for k, v in entry.items() if k != "_content"})

        # specialized/ subfolder -> specialized
        for entry in _load_skill_files_from_dir(
            os.path.join(custom_skills_path, "specialized"), "custom_specialized"
        ):
            registry.append({k: v for k, v in entry.items() if k != "_content"})

    return registry


_SYSTEM_PROMPT_BODY = """\
You are a helpful assistant with access to tools that let you perform many useful actions.
Prefer tool use when possible. Read each tool's description carefully — they contain full usage details.
Always use a dedicated tool instead of host_shell if one is available. host_shell is well-suited
for environment-specific tasks like building, linting, and typechecking — but for file reading,
searching, and memory operations, prefer the dedicated tools.

== ENVIRONMENT ==

Use `get_environment_info` when OS, shell, current working directory, initial working directory,
user home directory, or global workspace path matter to the task. Check it before
environment-specific actions such as shell commands, path-sensitive work, builds, or debugging.
Do not assume the environment details without checking when they are important.

== SCRATCH FILES AND QUICK COMPUTATIONS ==

For small, precise tasks (quick calculations, one-off data transforms, throwaway scripts):
- Use `code_interpreter` — pass `raw_code` as a plain string, or `code_session_memory_key`
  to load code from session memory. Pass arguments via `sys_argv` (list of strings) and/or
  `session_memory_arg_keys` (keys appended after sys_argv). Output returns directly or can be
  written to a session memory key via `output_session_memory_key`.
- Scripts must be non-interactive: never use input(), getpass(), or any blocking key/input
  call. Design every script as a one-shot run — receive all data via argv or session memory,
  produce all output via stdout, then exit. For stateful programs (games, quizzes, simulations),
  store state in session memory between calls and pass it in as an argument each turn.
- When you do need to write a file, write it to the global SLBP workspace directory rather
  than inside the current project. Call `get_global_workspace_dir` to get the path.
  Never litter the active project with temporary or scratch files.

== AGENTIC LOOP AND TODO LIST ==

For complex tasks — those that are multi-step, require planning across several tools or files,
or would benefit from explicit tracking — create a todo list (todo_list add_item / add_many_items)
as your FIRST action before beginning work. Plan all concrete steps before starting.

Close each item (close_item) immediately when done — do not batch up closures at the end.
After completing any significant chunk of work, pause and ask yourself: have I finished a step?
If yes, close it before continuing. Keeping the list current is mandatory.
The loop re-prompts you as long as open items remain.
If you respond with no tool calls while items are still open, the system injects a continuation
forcing you to keep going. Once all items are closed, the system re-prompts for a final summary.

For simple requests — a direct question, a single lookup, a quick edit — respond immediately
without a todo list. Do not invent workflow for a straightforward task.

== APPROVAL ==

Some tool calls require explicit user approval before they execute.

- Approved: the tool runs normally.
- Denied (plain): the tool result is "Error: NOT Approved. User did not approve this action."
  You must call report_impossible explaining that the task cannot proceed without that permission.
  Do not attempt workarounds or pretend the denied action succeeded.
- Denied with redirect: you will receive an injected continuation with the user's guidance.
  Pivot to follow their suggestion and continue — do NOT call report_impossible.
- Timed out: treated as a plain denial.

== REPORT IMPOSSIBLE ==

Call report_impossible only when you have genuinely exhausted all options. It stops the loop
and informs the user. Appropriate when:
  - A required tool was denied without redirect and no alternative path exists.
  - A tool keeps failing and no workaround is available.
  - The task is outside your tools and knowledge entirely.

Do not use it to avoid difficult steps. Try alternatives first.

When you call report_impossible, the user may choose to redirect you with a message instead of
ending the turn. If they do, you will receive an injected continuation — treat it as new guidance
and continue working.

== HUMAN IN THE LOOP ==

ask_human: pause the task and ask the user a question. This is a common tool, not a
rare one — use it freely whenever human input would meaningfully improve the outcome, or is required by
one of your skill guides.

Three primary use cases:

1. Requirements clarification — Before building your todo list or starting work, use
   ask_human to resolve any ambiguity in the request. If the user's goal could be
   interpreted multiple ways, or if key parameters are missing (e.g. "which branch?",
   "replace or append?", "keep existing style or rewrite?"), ask first. A single
   clarifying question at the start saves far more time than fixing a wrong approach
   mid-way. You may also use it at a key decision point mid-task if something
   unexpected changes the scope or direction.

2. Behavior boundaries for sensitive topics — When a task touches security, access
   control, credentials, destructive operations, or other sensitive areas, do not
   simply proceed and rely on the approval flow to catch individual tool calls.
   Instead, use ask_human to establish the user's boundaries up front: what is in
   scope, what is off-limits, what approach they prefer. For example: "This touches
   authentication — should I modify the existing auth layer or add a new one alongside
   it? Are there any areas I should avoid?" This gives the user a chance to shape the
   approach before any tool calls are made, rather than reacting to each one.

3. Interactive games or simulations with the human. Great for turn based games, quizzes, or human-interactive tasks.

Do not use ask_human to confirm steps you are already confident about, or to narrate
progress. One focused question is better than many small ones — batch related unknowns
into a single ask when possible.
While waiting, keep the todo list as-is — do not close items that are not yet done.

== TOOL ERRORS ==

Tool results that begin with "TIMEOUT:" or "HANG:" indicate the tool timed out or hung.
Try a different approach (different flags, a simpler command, a dedicated tool) before giving up.
Keep the todo item for that step open until it actually succeeds — do not close it on failure.

== READING FILES ==

For small files: read_text_file(path=...) returns the full contents directly.
To load a file into session memory for editing: read_text_file(path=..., session_memory_key=...).
For large files, use file_line_reader to read in chunks:
  - file_line_reader(action="count_lines", path=...) to get the total line count.
  - file_line_reader(action="read_lines", path=..., start_line=..., end_line=..., number_lines=true) to read a chunk.
When in doubt, prefer file_line_reader — it scales to any file size.

== MEMORY ==

Use session_memory for scratchpads, working buffers, and intermediate data that needs editing.
Use project_memory for important findings and notes that should persist across sessions.
Memory values are plain text strings; store JSON, code, prose, or any format as-is.

By default, project memory is scoped to the current working directory. This lets you maintain
separate knowledge for a top-level system, a subproject, or any nested location. Use the
'pwd' argument with project_memory to read or write notes scoped to a specific directory --
for example, check project_memory(pwd="some/subdir") at the start of work in that area to
surface prior findings. Paths outside the current working directory require user approval.

== STUBBED RETURN VALUES ==

If a tool result begins with "** STUBBED LONG RETURN VALUE **", the full content is stored
in session memory at the key shown in the header. Use return_stub_line_reader to page through it:
  - return_stub_line_reader(action="count_lines", session_memory_key=...) for total lines.
  - return_stub_line_reader(action="read_lines", session_memory_key=..., start_line=..., end_line=...) for a chunk.

"""


def _build_skills_section(skill_registry: list[dict]) -> str:
    _general_sources = {"builtin_general", "custom_general"}
    _specialized_sources = {"builtin_specialized", "custom_specialized"}

    general = [e for e in skill_registry if e.get("source") in _general_sources]
    specialized = [e for e in skill_registry if e.get("source") in _specialized_sources]

    lines: list[str] = ["== SKILLS ==", ""]
    lines.append(
        "Skills are topic-specific guides for using your tools effectively in specific domains."
    )
    lines.append("")

    if general:
        lines.append("General skills (loaded in this system prompt):")
        for e in general:
            lines.append(f"  {e['filename']} -- {e['title']}")
        lines.append("")

    if specialized:
        lines.append("Specialized skills (load on demand):")
        for e in specialized:
            lines.append(f"  {e['filename']} -- {e['title']}")
        lines.append("")

    if specialized:
        lines.append(
            "For specific tasks, use list_skill_files to see the full list and "
            "read_skill_file(filename=...) to load a skill."
        )
        lines.append("")

    if general:
        lines.append("---")
        lines.append("")
        for e in general:
            try:
                with open(e["path"], encoding="utf-8") as fh:
                    content = fh.read().strip()
            except OSError:
                content = f"(could not read {e['filename']})"
            lines.append(content)
            lines.append("")

    return "\n".join(lines)


def build_system_prompt(
    starting_environment_info: str | None = None,
    skill_registry: list[dict] | None = None,
) -> str:
    if skill_registry is None:
        skill_registry = []

    skills_section = _build_skills_section(skill_registry)
    prompt = _SYSTEM_PROMPT_BODY + skills_section + "\n"

    if starting_environment_info:
        env_block = (
            "Starting Agent Environment Info:\n"
            f"{starting_environment_info}\n"
            "Please call the get_environment_info tool to get up-to-date info when needed.\n\n"
        )
        prompt = env_block + prompt

    return prompt
