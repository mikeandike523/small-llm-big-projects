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
            name
            for name in os.listdir(directory)
            if os.path.isdir(os.path.join(directory, name))
        )
    except OSError:
        return []


def _load_manifest_entries(manifest_path: str) -> dict[str, dict]:
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except OSError as exc:
        raise SkillManifestError(
            f"Could not read skills manifest at {manifest_path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise SkillManifestError(
            f"Invalid JSON in skills manifest at {manifest_path}: {exc}"
        ) from exc

    if isinstance(raw, dict) and "skills" in raw:
        raw = raw["skills"]

    if not isinstance(raw, dict):
        raise SkillManifestError(
            f"skills.json at {manifest_path} must be an object mapping skill ids to metadata."
        )

    entries: dict[str, dict] = {}
    for skill_id, meta in raw.items():
        if not isinstance(skill_id, str) or not skill_id.strip():
            raise SkillManifestError(
                f"skills.json at {manifest_path} contains an invalid skill id key."
            )
        if not isinstance(meta, dict):
            raise SkillManifestError(
                f"skills.json at {manifest_path} entry {skill_id!r} must be an object."
            )

        dependencies = meta.get("dependencies", [])
        if not isinstance(dependencies, list) or any(
            not isinstance(dep, str) for dep in dependencies
        ):
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


def _load_skill_entries_from_directory(
    directory: str, source: str, id_prefix: str = ""
) -> list[dict]:
    markdown_files = _list_markdown_files(directory)
    manifest_path = os.path.join(directory, "skills.json")
    has_manifest = os.path.isfile(manifest_path)

    if not markdown_files and not has_manifest:
        return []

    expected_ids = {
        f"{id_prefix}{os.path.splitext(filename)[0]}" for filename in markdown_files
    }

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
            raise SkillManifestError(
                f"Could not read skill file at {path}: {exc}"
            ) from exc

        inferred_name = parse_skill_title(content)
        inferred_blurb = parse_skill_blurb(content)
        meta = manifest_entries.get(skill_id, {})
        entries.append(
            {
                "id": skill_id,
                "name": meta.get("name") or inferred_name,
                "title": meta.get("name") or inferred_name,
                "blurb": meta.get("blurb") or inferred_blurb,
                "filename": filename,
                "path": path,
                "source": source,
                "dependencies": list(meta.get("dependencies", [])),
                "autoload": bool(meta.get("autoload", False)),
            }
        )
    return entries


def _load_skill_tree(
    directory: str,
    source: str,
    recursive_subdirs: bool,
    id_prefix: str = "",
) -> list[dict]:
    entries = _load_skill_entries_from_directory(
        directory, source=source, id_prefix=id_prefix
    )
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
        missing = [
            dep for dep in entry.get("dependencies", []) if dep not in entries_by_id
        ]
        if missing:
            raise SkillManifestError(
                f"Skill {entry['id']!r} references unknown dependencies: {', '.join(missing)}."
            )


def build_skill_registry(custom_skills_path: str | None = None) -> list[dict]:
    """Return the manifest-backed built-in/custom skill registry."""
    builtin_registry = _load_skill_tree(
        _BUILT_IN_SKILLS_DIR, source="builtin", recursive_subdirs=False
    )
    custom_registry: list[dict] = []
    if custom_skills_path:
        custom_registry = _load_skill_tree(
            custom_skills_path, source="custom", recursive_subdirs=True
        )

        builtin_ids = {entry["id"] for entry in builtin_registry}
        overridden = sorted(
            entry["id"] for entry in custom_registry if entry["id"] in builtin_ids
        )
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


def resolve_skill_dependency_closure(
    skill_registry: list[dict], staged_skill_ids: list[str]
) -> list[dict]:
    entries_by_id = {entry["id"]: entry for entry in skill_registry}
    resolved: list[dict] = []
    seen: set[str] = set()

    def visit(skill_id: str) -> None:
        if skill_id in seen:
            return
        entry = entries_by_id.get(skill_id)
        if entry is None:
            raise SkillManifestError(
                f"Unknown skill id during dependency resolution: {skill_id!r}."
            )
        seen.add(skill_id)
        for dep in entry.get("dependencies", []):
            visit(dep)
        resolved.append(entry)

    for skill_id in staged_skill_ids:
        visit(skill_id)
    return resolved


_SYSTEM_PROMPT_BODY = """\
You are a helpful assistant with access to tools that let you perform many useful actions.
Prefer tool use when possible. Read each tool's description carefully — they contain full usage details.
Always use a dedicated tool instead of host_shell if one is available.

== ENVIRONMENT ==

Use `get_environment_info` when OS, shell, current working directory, or global workspace path
matter to the task. Check it before shell commands, path-sensitive work, builds, or debugging.

== SCRATCH FILES AND QUICK COMPUTATIONS ==

For small precise tasks: use `code_interpreter` — pass `raw_code` (inline string) or
`code_session_memory_key`. Pass arguments via `sys_argv` and/or `session_memory_arg_keys`.
Output returns directly or write to `output_session_memory_key`. Scripts must be non-interactive.
For files that must persist, write to the global workspace (`get_global_workspace_dir`), not the active project.

== AGENTIC LOOP AND TODO LIST ==

For complex tasks — multi-step, requiring planning across several tools or files — create a todo
list (todo_list add_item / add_many_items) as your FIRST action before beginning work.

Close each item (close_item) immediately when done — do not batch closures. The loop re-prompts
you as long as open items remain. If you respond with no tool calls while items are still open,
a continuation is injected. Once all items are closed, you are re-prompted for a final summary.

If remaining open items are genuinely impossible to complete, call `report_impossible` with a
clear reason. For simple requests — a direct question, a single lookup, a quick edit — respond
immediately without a todo list.

== APPROVAL ==

Some tool calls require explicit user approval before they execute.

- Approved: the tool runs normally.
- Denied (plain): result is “Error: NOT Approved. User did not approve this action.” If the task
  cannot proceed without that permission and no alternative exists, state this clearly and stop.
- Denied with redirect: you will receive an injected continuation with the user's guidance. Pivot.
- Timed out: treated as a plain denial.

== QUESTIONS AND IMPOSSIBILITY ==

If you need clarification or permission before proceeding, state your question clearly as your
final response and stop — do not use tools. The user will follow up with full context.

One focused question is better than several — batch related unknowns into a single message.

If you have genuinely exhausted all options and the task cannot be completed, explain why clearly.
Do not give up to avoid difficult steps — try alternatives first.

== TOOL ERRORS ==

Results beginning with “TIMEOUT:” or “HANG:” indicate the tool timed out or hung. Try a different
approach before giving up. Keep the todo item open until the step actually succeeds.

== MEMORY ==

Use session_memory for scratchpads, working buffers, and intermediate data. Values are plain text.

== STUBBED RETURN VALUES ==

If a tool result begins with “** STUBBED LONG RETURN VALUE **”, the full content is stored in
session memory at the key shown in the header. Use with session_memory or line_reader:
  - session_memory(action=”search_by_regex”, key=..., pattern=...) to search directly.
  - line_reader(action=”count_lines”, session_memory_key=...) for total lines.
  - line_reader(action=”read_lines”, session_memory_key=..., start_line=..., end_line=...) for chunks.

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
