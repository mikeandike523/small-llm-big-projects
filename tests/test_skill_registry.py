from pathlib import Path

import pytest

from src.logic.system_prompt import (
    SkillManifestError,
    build_skill_registry,
    get_autoload_skill_entries,
    resolve_skill_dependency_closure,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_implicit_manifest_and_subdir_prefixing(tmp_path: Path) -> None:
    _write(tmp_path / "local_notes.md", "# Local Notes\n\nUseful local guidance.\n")
    _write(
        tmp_path / "python" / "linting.md",
        "# Python Linting\n\nLint Python code before submission.\n",
    )
    _write(
        tmp_path / "python" / "skills.json",
        """{
  "python_linting": {
    "name": "Python Linting",
    "blurb": "Lint Python code before submission.",
    "dependencies": [],
    "autoload": false
  }
}""",
    )

    registry = build_skill_registry(str(tmp_path))
    custom_entries = {
        entry["id"]: entry for entry in registry if entry["source"] == "custom"
    }

    assert "local_notes" in custom_entries
    assert custom_entries["local_notes"]["autoload"] is False
    assert custom_entries["local_notes"]["name"] == "Local Notes"
    assert "python_linting" in custom_entries
    assert custom_entries["python_linting"]["filename"] == "linting.md"


def test_manifest_must_match_directory_files(tmp_path: Path) -> None:
    _write(tmp_path / "alpha.md", "# Alpha\n")
    _write(
        tmp_path / "skills.json",
        """{
  "beta": {
    "name": "Beta",
    "blurb": "Mismatch",
    "dependencies": [],
    "autoload": false
  }
}""",
    )

    with pytest.raises(SkillManifestError, match="does not match the markdown files"):
        build_skill_registry(str(tmp_path))


def test_custom_skill_cannot_override_builtin(tmp_path: Path) -> None:
    _write(tmp_path / "coding.md", "# Not Allowed\n")

    with pytest.raises(SkillManifestError, match="may not override built-in skills"):
        build_skill_registry(str(tmp_path))


def test_exclude_builtin_skills_removes_them_from_registry(tmp_path: Path) -> None:
    _write(
        tmp_path / "skills.json",
        '{"excludeBuiltinSkills": ["coding"]}',
    )

    registry = build_skill_registry(str(tmp_path))
    ids = {e["id"] for e in registry}
    assert "coding" not in ids
    assert "web_browsing" in ids


def test_exclude_builtin_skills_alongside_custom_skills(tmp_path: Path) -> None:
    _write(tmp_path / "my_tool.md", "# My Tool\n\nDoes things.\n")
    _write(
        tmp_path / "skills.json",
        """{
  "excludeBuiltinSkills": ["coding"],
  "my_tool": {
    "name": "My Tool",
    "blurb": "Does things.",
    "dependencies": [],
    "autoload": false
  }
}""",
    )

    registry = build_skill_registry(str(tmp_path))
    ids = {e["id"] for e in registry}
    assert "coding" not in ids
    assert "web_browsing" in ids
    assert "my_tool" in ids


def test_exclude_builtin_skills_unknown_id_is_silently_ignored(tmp_path: Path) -> None:
    _write(
        tmp_path / "skills.json",
        '{"excludeBuiltinSkills": ["nonexistent_skill"]}',
    )

    registry = build_skill_registry(str(tmp_path))
    ids = {e["id"] for e in registry}
    assert "coding" in ids
    assert "web_browsing" in ids


def test_exclude_builtin_skills_invalid_type_raises(tmp_path: Path) -> None:
    _write(
        tmp_path / "skills.json",
        '{"excludeBuiltinSkills": "coding"}',
    )

    with pytest.raises(SkillManifestError, match="must be a list of strings"):
        build_skill_registry(str(tmp_path))


def test_autoload_and_cycles_resolve_without_recursing_forever() -> None:
    registry = [
        {
            "id": "alpha",
            "name": "Alpha",
            "title": "Alpha",
            "blurb": "Alpha",
            "filename": "alpha.md",
            "path": "alpha.md",
            "source": "custom",
            "dependencies": ["beta"],
            "autoload": True,
        },
        {
            "id": "beta",
            "name": "Beta",
            "title": "Beta",
            "blurb": "Beta",
            "filename": "beta.md",
            "path": "beta.md",
            "source": "custom",
            "dependencies": ["alpha"],
            "autoload": False,
        },
    ]

    autoloaded = get_autoload_skill_entries(registry)
    resolved = resolve_skill_dependency_closure(registry, ["alpha"])

    assert {entry["id"] for entry in autoloaded} == {"alpha", "beta"}
    assert {entry["id"] for entry in resolved} == {"alpha", "beta"}
