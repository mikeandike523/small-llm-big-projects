import uuid
from pathlib import Path

import pytest

from src.tools import load_custom_tools, reload_custom_tools


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


_TOOL_FILE_TEMPLATE = """
DEFINITION = {{
    "type": "function",
    "function": {{
        "name": "{name}",
        "description": "test tool",
        "parameters": {{
            "type": "object",
            "properties": {{}},
            "additionalProperties": False,
        }},
    }},
}}


def execute(args, session_data, special_resources=None):
    return "ok"
"""


def _tool_file(name: str) -> str:
    return _TOOL_FILE_TEMPLATE.format(name=name)


def _prefix() -> str:
    return uuid.uuid4().hex[:8]


def test_folder_name_is_default_namespace(tmp_path: Path) -> None:
    _write(tmp_path / "web_browsing" / "__init__.py", "")
    _write(tmp_path / "web_browsing" / "do_thing.py", _tool_file("do_thing"))

    result = load_custom_tools(
        str(tmp_path),
        session_prefix=_prefix(),
        known_skill_ids=frozenset({"web_browsing"}),
    )

    assert set(result.by_skill.keys()) == {"web_browsing"}
    defs, tool_map = result.by_skill["web_browsing"]
    assert [d["function"]["name"] for d in defs] == ["web_browsing_do_thing"]
    assert "web_browsing_do_thing" in tool_map


def test_explicit_tool_namespace_overrides_folder_name(tmp_path: Path) -> None:
    _write(tmp_path / "folder_name" / "__init__.py", 'TOOL_NAMESPACE = "custom_ns"\n')
    _write(tmp_path / "folder_name" / "do_thing.py", _tool_file("do_thing"))

    result = load_custom_tools(
        str(tmp_path),
        session_prefix=_prefix(),
        known_skill_ids=frozenset({"custom_ns"}),
    )

    assert set(result.by_skill.keys()) == {"custom_ns"}
    defs, _ = result.by_skill["custom_ns"]
    assert [d["function"]["name"] for d in defs] == ["custom_ns_do_thing"]


def test_unscoped_root_tool_has_no_prefix_and_is_not_skill_gated(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "root_tool.py", _tool_file("root_tool"))

    result = load_custom_tools(
        str(tmp_path),
        session_prefix=_prefix(),
        known_skill_ids=frozenset(),  # no skills at all — must not matter for unscoped
    )

    assert [d["function"]["name"] for d in result.unscoped_defs] == ["root_tool"]
    assert "root_tool" in result.unscoped_map
    assert result.by_skill == {}


def test_namespace_not_a_known_skill_id_hard_fails(tmp_path: Path) -> None:
    _write(tmp_path / "mystery" / "__init__.py", "")
    _write(tmp_path / "mystery" / "do_thing.py", _tool_file("do_thing"))

    with pytest.raises(RuntimeError, match="does not match any known skill id"):
        load_custom_tools(
            str(tmp_path),
            session_prefix=_prefix(),
            known_skill_ids=frozenset({"other_skill"}),
        )


def test_known_skill_ids_none_skips_validation(tmp_path: Path) -> None:
    _write(tmp_path / "mystery" / "__init__.py", "")
    _write(tmp_path / "mystery" / "do_thing.py", _tool_file("do_thing"))

    result = load_custom_tools(str(tmp_path), session_prefix=_prefix())

    assert set(result.by_skill.keys()) == {"mystery"}


def test_unscoped_tool_colliding_with_builtin_hard_fails(tmp_path: Path) -> None:
    _write(tmp_path / "get_pwd.py", _tool_file("get_pwd"))

    with pytest.raises(RuntimeError, match="collides with an existing tool"):
        load_custom_tools(str(tmp_path), session_prefix=_prefix())


def test_helper_file_without_definition_is_skipped_not_a_tool(tmp_path: Path) -> None:
    _write(tmp_path / "web_browsing" / "__init__.py", "")
    _write(tmp_path / "web_browsing" / "do_thing.py", _tool_file("do_thing"))
    _write(
        tmp_path / "web_browsing" / "_helpers.py",
        "def format_target(x):\n    return x\n",
    )
    _write(tmp_path / "_root_helper.py", "VALUE = 1\n")

    result = load_custom_tools(
        str(tmp_path),
        session_prefix=_prefix(),
        known_skill_ids=frozenset({"web_browsing"}),
    )

    defs, _ = result.by_skill["web_browsing"]
    assert [d["function"]["name"] for d in defs] == ["web_browsing_do_thing"]
    assert result.unscoped_defs == []


def test_reload_reimports_changed_tool_and_import_local_helper(tmp_path: Path) -> None:
    prefix = _prefix()
    helper = tmp_path / "_helper.py"
    tool = tmp_path / "root_tool.py"
    _write(helper, 'VALUE = "before"\n')
    _write(
        tool,
        "from src.tools import import_local\n"
        'HELPER = import_local("_helper.py")\n'
        + _tool_file("root_tool").replace('return "ok"', "return HELPER.VALUE"),
    )
    first = load_custom_tools(str(tmp_path), session_prefix=prefix)
    old_module = first.unscoped_map["root_tool"]
    assert old_module.execute({}, {}) == "before"

    _write(helper, 'VALUE = "after"\n')
    second = reload_custom_tools(str(tmp_path), session_prefix=prefix)

    assert second.unscoped_map["root_tool"].execute({}, {}) == "after"
    assert old_module.execute({}, {}) == "before"


def test_failed_reload_leaves_previous_tool_generation_usable(tmp_path: Path) -> None:
    prefix = _prefix()
    tool = tmp_path / "root_tool.py"
    _write(tool, _tool_file("root_tool"))
    first = load_custom_tools(str(tmp_path), session_prefix=prefix)
    old_module = first.unscoped_map["root_tool"]

    _write(tool, "this is not valid python")
    with pytest.raises(RuntimeError, match="Failed to import custom tool"):
        reload_custom_tools(str(tmp_path), session_prefix=prefix)

    assert old_module.execute({}, {}) == "ok"
