import json
import os

_BUILT_IN_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "built_in_skills")


class SkillManifestError(RuntimeError):
    """Raised when skill discovery or manifest validation fails."""


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


def parse_skill_blurb(content: str) -> str:
    lines = content.splitlines()
    heading_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            heading_idx = i
            break

    start_idx = (heading_idx + 1) if heading_idx is not None else 0
    blurb_lines: list[str] = []
    started = False
    for line in lines[start_idx:]:
        stripped = line.strip()
        if not stripped:
            if started:
                break
            continue
        if stripped.startswith("#"):
            if started:
                break
            continue
        blurb_lines.append(stripped)
        started = True
        if len(blurb_lines) >= 3:
            break

    if not blurb_lines:
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                blurb_lines = [stripped]
                break

    blurb = " ".join(blurb_lines).strip()
    if len(blurb) > 240:
        blurb = blurb[:237].rstrip() + "..."
    return blurb


def _read_skill_content(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _list_markdown_files(directory: str) -> list[str]:
    try:
        return sorted(f for f in os.listdir(directory) if f.lower().endswith(".md"))
    except OSError:
        return []


def _list_subdirs(directory: str) -> list[str]:
    try:
        return sorted(
            name for name in os.listdir(directory)
            if os.path.isdir(os.path.join(directory, name))
        )
    except OSError:
        return []


def _load_manifest_entries(manifest_path: str) -> dict[str, dict]:
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except OSError as exc:
        raise SkillManifestError(f"Could not read skills manifest at {manifest_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SkillManifestError(f"Invalid JSON in skills manifest at {manifest_path}: {exc}") from exc

    if isinstance(raw, dict) and "skills" in raw:
        raw = raw["skills"]

    if not isinstance(raw, dict):
        raise SkillManifestError(
            f"skills.json at {manifest_path} must be an object mapping skill ids to metadata."
        )

    entries: dict[str, dict] = {}
    for skill_id, meta in raw.items():
        if not isinstance(skill_id, str) or not skill_id.strip():
            raise SkillManifestError(f"skills.json at {manifest_path} contains an invalid skill id key.")
        if not isinstance(meta, dict):
            raise SkillManifestError(
                f"skills.json at {manifest_path} entry {skill_id!r} must be an object."
            )

        dependencies = meta.get("dependencies", [])
        if not isinstance(dependencies, list) or any(not isinstance(dep, str) for dep in dependencies):
            raise SkillManifestError(
                f"skills.json at {manifest_path} entry {skill_id!r} has invalid dependencies."
            )

        autoload = meta.get("autoload", False)
        if not isinstance(autoload, bool):
            raise SkillManifestError(
                f"skills.json at {manifest_path} entry {skill_id!r} has non-boolean autoload."
            )

        name = meta.get("name")
        blurb = meta.get("blurb")
        if name is not None and not isinstance(name, str):
            raise SkillManifestError(
                f"skills.json at {manifest_path} entry {skill_id!r} has non-string name."
            )
        if blurb is not None and not isinstance(blurb, str):
            raise SkillManifestError(
                f"skills.json at {manifest_path} entry {skill_id!r} has non-string blurb."
            )

        entries[skill_id] = {
            "name": (name or "").strip(),
            "blurb": (blurb or "").strip(),
            "dependencies": dependencies,
            "autoload": autoload,
        }

    return entries


def _load_skill_entries_from_directory(directory: str, source: str, id_prefix: str = "") -> list[dict]:
    markdown_files = _list_markdown_files(directory)
    manifest_path = os.path.join(directory, "skills.json")
    has_manifest = os.path.isfile(manifest_path)

    if not markdown_files and not has_manifest:
        return []

    expected_ids = {f"{id_prefix}{os.path.splitext(filename)[0]}" for filename in markdown_files}

    if has_manifest:
        manifest_entries = _load_manifest_entries(manifest_path)
        manifest_ids = set(manifest_entries)
        missing_from_manifest = sorted(expected_ids - manifest_ids)
        extra_in_manifest = sorted(manifest_ids - expected_ids)
        if missing_from_manifest or extra_in_manifest:
            raise SkillManifestError(
                f"skills.json at {manifest_path} does not match the markdown files in {directory}. "
                f"Missing ids: {missing_from_manifest or 'none'}. "
                f"Extra ids: {extra_in_manifest or 'none'}."
            )
    else:
        manifest_entries = {}

    entries: list[dict] = []
    for filename in markdown_files:
        path = os.path.join(directory, filename)
        skill_stem = os.path.splitext(filename)[0]
        skill_id = f"{id_prefix}{skill_stem}"
        try:
            content = _read_skill_content(path)
        except OSError as exc:
            raise SkillManifestError(f"Could not read skill file at {path}: {exc}") from exc

        inferred_name = parse_skill_title(content)
        inferred_blurb = parse_skill_blurb(content)
        meta = manifest_entries.get(skill_id, {})
        entries.append({
            "id": skill_id,
            "name": meta.get("name") or inferred_name,
            "title": meta.get("name") or inferred_name,
            "blurb": meta.get("blurb") or inferred_blurb,
            "filename": filename,
            "path": path,
            "source": source,
            "dependencies": list(meta.get("dependencies", [])),
            "autoload": bool(meta.get("autoload", False)),
        })
    return entries


def _load_skill_tree(
    directory: str,
    source: str,
    recursive_subdirs: bool,
    id_prefix: str = "",
) -> list[dict]:
    entries = _load_skill_entries_from_directory(directory, source=source, id_prefix=id_prefix)
    if not recursive_subdirs:
        return entries

    for subdir_name in _list_subdirs(directory):
        subdir_path = os.path.join(directory, subdir_name)
        entries.extend(
            _load_skill_tree(
                subdir_path,
                source=source,
                recursive_subdirs=True,
                id_prefix=f"{id_prefix}{subdir_name}_",
            )
        )
    return entries


def _validate_registry_entries(registry: list[dict]) -> None:
    entries_by_id: dict[str, dict] = {}
    for entry in registry:
        skill_id = entry["id"]
        if skill_id in entries_by_id:
            prior = entries_by_id[skill_id]
            raise SkillManifestError(
                f"Duplicate skill id {skill_id!r} detected between {prior['path']} and {entry['path']}."
            )
        entries_by_id[skill_id] = entry

    for entry in registry:
        missing = [dep for dep in entry.get("dependencies", []) if dep not in entries_by_id]
        if missing:
            raise SkillManifestError(
                f"Skill {entry['id']!r} references unknown dependencies: {', '.join(missing)}."
            )


def build_skill_registry(custom_skills_path: str | None = None) -> list[dict]:
    """Return the manifest-backed built-in/custom skill registry."""
    builtin_registry = _load_skill_tree(_BUILT_IN_SKILLS_DIR, source="builtin", recursive_subdirs=False)
    custom_registry: list[dict] = []
    if custom_skills_path:
        custom_registry = _load_skill_tree(custom_skills_path, source="custom", recursive_subdirs=True)

        builtin_ids = {entry["id"] for entry in builtin_registry}
        overridden = sorted(entry["id"] for entry in custom_registry if entry["id"] in builtin_ids)
        if overridden:
            raise SkillManifestError(
                "Custom skills may not override built-in skills. "
                f"Conflicting ids: {', '.join(overridden)}."
            )

    registry = builtin_registry + custom_registry
    _validate_registry_entries(registry)
    return registry


def get_autoload_skill_entries(skill_registry: list[dict]) -> list[dict]:
    return resolve_skill_dependency_closure(
        skill_registry,
        [entry["id"] for entry in skill_registry if entry.get("autoload")],
    )


def get_selector_candidate_entries(skill_registry: list[dict]) -> list[dict]:
    return [entry for entry in skill_registry if not entry.get("autoload")]


def resolve_skill_dependency_closure(skill_registry: list[dict], staged_skill_ids: list[str]) -> list[dict]:
    entries_by_id = {entry["id"]: entry for entry in skill_registry}
    resolved: list[dict] = []
    seen: set[str] = set()

    def visit(skill_id: str) -> None:
        if skill_id in seen:
            return
        entry = entries_by_id.get(skill_id)
        if entry is None:
            raise SkillManifestError(f"Unknown skill id during dependency resolution: {skill_id!r}.")
        seen.add(skill_id)
        for dep in entry.get("dependencies", []):
            visit(dep)
        resolved.append(entry)

    for skill_id in staged_skill_ids:
        visit(skill_id)
    return resolved


_SYSTEM_PROMPT_BODY = """\
You are a helpful assistant with access to tools that let you perform many useful actions.
Prefer tool use when possible. Read each tool's description carefully â€” they contain full usage details.
Always use a dedicated tool instead of host_shell if one is available. host_shell is well-suited
for environment-specific tasks like building, linting, and typechecking â€” but for file reading,
searching, and memory operations, prefer the dedicated tools.

== SCRIPTS AND INTERACTIVE TASKS ==

For games, quizzes, simulations, and other interactive tasks: do NOT use ask_human to get
per-turn input. Instead, process the state using code_interpreter with session memory, then
respond to the user with the updated state and prompt them to enter their next action as a new
message. Each user message is one turn â€” design your logic accordingly.

== ENVIRONMENT ==

Use `get_environment_info` when OS, shell, current working directory, initial working directory,
user home directory, or global workspace path matter to the task. Check it before
environment-specific actions such as shell commands, path-sensitive work, builds, or debugging.
Do not assume the environment details without checking when they are important.

== SCRATCH FILES AND QUICK COMPUTATIONS ==

For small, precise tasks (quick calculations, one-off data transforms, throwaway scripts):
- Use `code_interpreter` â€” pass `raw_code` as a plain string, or `code_session_memory_key`
  to load code from session memory. Pass arguments via `sys_argv` (list of strings) and/or
  `session_memory_arg_keys` (keys appended after sys_argv). Output returns directly or can be
  written to a session memory key via `output_session_memory_key`.
- Scripts must be non-interactive: never use input(), getpass(), or any blocking key/input
  call. Design every script as a one-shot run â€” receive all data via argv or session memory,
  produce all output via stdout, then exit. For stateful programs (games, quizzes, simulations),
  store state in session memory between calls and pass it in as an argument each turn.
- When you do need to write a file, write it to the global SLBP workspace directory rather
  than inside the current project. Call `get_global_workspace_dir` to get the path.
  Never litter the active project with temporary or scratch files.

== AGENTIC LOOP AND TODO LIST ==

For complex tasks â€” those that are multi-step, require planning across several tools or files,
or would benefit from explicit tracking â€” create a todo list (todo_list add_item / add_many_items)
as your FIRST action before beginning work. Plan all concrete steps before starting.

Close each item (close_item) immediately when done â€” do not batch up closures at the end.
After completing any significant chunk of work, pause and ask yourself: have I finished a step?
If yes, close it before continuing. Keeping the list current is mandatory.
The loop re-prompts you as long as open items remain.
If you respond with no tool calls while items are still open, the system injects a continuation
forcing you to keep going. Once all items are closed, the system re-prompts for a final summary.

For simple requests â€” a direct question, a single lookup, a quick edit â€” respond immediately
without a todo list. Do not invent workflow for a straightforward task.

== APPROVAL ==

Some tool calls require explicit user approval before they execute.

- Approved: the tool runs normally.
- Denied (plain): the tool result is "Error: NOT Approved. User did not approve this action."
  You must call report_impossible explaining that the task cannot proceed without that permission.
  Do not attempt workarounds or pretend the denied action succeeded.
- Denied with redirect: you will receive an injected continuation with the user's guidance.
  Pivot to follow their suggestion and continue â€” do NOT call report_impossible.
- Timed out: treated as a plain denial.

== REPORT IMPOSSIBLE ==

Call report_impossible only when you have genuinely exhausted all options. It stops the loop
and informs the user. Appropriate when:
  - A required tool was denied without redirect and no alternative path exists.
  - A tool keeps failing and no workaround is available.
  - The task is outside your tools and knowledge entirely.

Do not use it to avoid difficult steps. Try alternatives first.

When you call report_impossible, the user may choose to redirect you with a message instead of
ending the turn. If they do, you will receive an injected continuation â€” treat it as new guidance
and continue working.

== HUMAN IN THE LOOP ==

ask_human: pause the task and ask the user a question. Use it sparingly â€” only when
human input is genuinely required and cannot be inferred from context.

Two appropriate use cases:

1. Requirements clarification â€” Before building your todo list or starting work, use
   ask_human to resolve any ambiguity in the request. If the user's goal could be
   interpreted multiple ways, or if key parameters are missing (e.g. "which branch?",
   "replace or append?", "keep existing style or rewrite?"), ask first. A single
   clarifying question at the start saves far more time than fixing a wrong approach
   mid-way. You may also use it at a key decision point mid-task if something
   unexpected changes the scope or direction.

2. Behavior boundaries for sensitive topics â€” When a task touches security, access
   control, credentials, destructive operations, or other sensitive areas, do not
   simply proceed and rely on the approval flow to catch individual tool calls.
   Instead, use ask_human to establish the user's boundaries up front: what is in
   scope, what is off-limits, what approach they prefer. For example: "This touches
   authentication â€” should I modify the existing auth layer or add a new one alongside
   it? Are there any areas I should avoid?" This gives the user a chance to shape the
   approach before any tool calls are made, rather than reacting to each one.

Do not use ask_human to confirm steps you are already confident about, to narrate
progress, or to collect per-turn input for games, quizzes, or simulations â€” see the
SCRIPTS AND INTERACTIVE TASKS section for how to handle those.
One focused question is better than many small ones â€” batch related unknowns into a
single ask when possible.
While waiting, keep the todo list as-is â€” do not close items that are not yet done.

== TOOL ERRORS ==

Tool results that begin with "TIMEOUT:" or "HANG:" indicate the tool timed out or hung.
Try a different approach (different flags, a simpler command, a dedicated tool) before giving up.
Keep the todo item for that step open until it actually succeeds â€” do not close it on failure.

== READING AND EDITING FILES ==

For small files: read_text_file(path=...) returns the full contents directly.
To load a file into session memory for editing: read_text_file(path=..., session_memory_key=...).
For large files, use file_line_reader to read in chunks:
  - file_line_reader(action=”count_lines”, path=...) to get the total line count.
  - file_line_reader(action=”read_lines”, path=..., start_line=..., end_line=..., number_lines=true) to read a chunk.
When in doubt, prefer file_line_reader â€” it scales to any file size.

We encourage using session memory to edit files, but you can also use the text_editor tool to
read and patch files directly (text_editor(filepath=..., action=...)). At the start of a new task
that writes files directly, check each target file once with git (e.g. git status --short <file>)
-- not before every edit in a multi-step sequence. If a file has unstaged or uncommitted staged
changes, warn the user and use the `ask_human` tool for approval before overwriting.

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
in session memory at the key shown in the header. Stubs ARE session memory -- the key can be
used with any session_memory action, including search_by_regex to find patterns without reading
everything. You can also page through with return_stub_line_reader:
  - session_memory(action="search_by_regex", key=..., pattern=...) to search the stub content directly.
  - return_stub_line_reader(action="count_lines", session_memory_key=...) for total lines.
  - return_stub_line_reader(action="read_lines", session_memory_key=..., start_line=..., end_line=...) for a chunk.

"""


def build_injected_skills_section(selected_entries: list[dict]) -> str:
    """Build the Skills section injected into the system prompt for the current turn."""
    if not selected_entries:
        return ""

    lines: list[str] = ["== SKILLS ==", ""]
    lines.append(
        "The following skill guides have been loaded for this turn. "
        "Follow their instructions when relevant."
    )
    lines.append("")
    for entry in selected_entries:
        try:
            content = _read_skill_content(entry["path"]).strip()
        except OSError:
            content = f"(could not read {entry['filename']})"
        lines.append(content)
        lines.append("")

    return "\n".join(lines)


def build_system_prompt(
    starting_environment_info: str | None = None,
    autoload_entries: list[dict] | None = None,
) -> str:
    prompt = _SYSTEM_PROMPT_BODY

    if autoload_entries:
        prompt += "\n" + build_injected_skills_section(autoload_entries)

    if starting_environment_info:
        env_block = (
            "Starting Agent Environment Info:\n"
            f"{starting_environment_info}\n"
            "Please call the get_environment_info tool to get up-to-date info when needed.\n\n"
        )
        prompt = env_block + prompt

    return prompt
