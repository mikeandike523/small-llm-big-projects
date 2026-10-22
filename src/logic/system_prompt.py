import json
import os

from src.logic.prompt_placeholders import PlaceholderContext, interpolate_placeholders
from src.logic.system_prompt_body import _SYSTEM_PROMPT_BODY

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

    if isinstance(raw, dict):
        raw = {k: v for k, v in raw.items() if k != "excludeBuiltinSkills"}

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


def _read_excluded_builtin_skill_ids(custom_skills_path: str) -> list[str]:
    manifest_path = os.path.join(custom_skills_path, "skills.json")
    if not os.path.isfile(manifest_path):
        return []
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict):
        return []
    excluded = raw.get("excludeBuiltinSkills", [])
    if not isinstance(excluded, list) or not all(isinstance(x, str) for x in excluded):
        raise SkillManifestError(
            f"excludeBuiltinSkills in {manifest_path} must be a list of strings."
        )
    return excluded


def build_skill_registry(custom_skills_path: str | None = None) -> list[dict]:
    """Return the manifest-backed built-in/custom skill registry."""
    builtin_registry = _load_skill_tree(
        _BUILT_IN_SKILLS_DIR, source="builtin", recursive_subdirs=False
    )
    custom_registry: list[dict] = []
    if custom_skills_path:
        excluded_ids = set(_read_excluded_builtin_skill_ids(custom_skills_path))
        if excluded_ids:
            builtin_registry = [
                e for e in builtin_registry if e["id"] not in excluded_ids
            ]

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


def build_injected_skills_section(
    selected_entries: list[dict], placeholders: PlaceholderContext | None = None
) -> str:
    """Build the Skills section injected into the system prompt for the current turn.
    Skill files are re-read on every call, so placeholders reflect the file as it is now.
    """
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
            content = interpolate_placeholders(
                _read_skill_content(entry["path"]).strip(),
                placeholders,
                source=entry["filename"],
            )
        except OSError:
            content = f"(could not read {entry['filename']})"
        lines.append(content)
        lines.append("")

    return "\n".join(lines)


def build_system_prompt(
    starting_environment_info: str | None = None,
    autoload_entries: list[dict] | None = None,
    placeholders: PlaceholderContext | None = None,
) -> str:
    prompt = interpolate_placeholders(
        _SYSTEM_PROMPT_BODY, placeholders, source="system prompt"
    )

    if autoload_entries:
        prompt += "\n" + build_injected_skills_section(autoload_entries, placeholders)

    if starting_environment_info:
        env_block = (
            "Starting Agent Environment Info:\n"
            f"{starting_environment_info}\n"
            "Please call the get_environment_info tool to get up-to-date info when needed.\n\n"
        )
        prompt = env_block + prompt

    return prompt
