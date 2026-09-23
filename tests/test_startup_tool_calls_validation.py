from src.utils.startup_tool_calls import validate_startup_tool_calls


class _FakeModule:
    def __init__(self, definition: dict) -> None:
        self.DEFINITION = definition


def _tool(name: str, required: list[str] | None = None) -> _FakeModule:
    return _FakeModule(
        {
            "type": "function",
            "function": {
                "name": name,
                "description": "test",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string"},
                    },
                    "required": required or [],
                    "additionalProperties": False,
                },
            },
        }
    )


def test_valid_calls_pass() -> None:
    tool_map = {"do_thing": _tool("do_thing", required=["target"])}
    calls = [{"name": "do_thing", "args": {"target": "x"}}]
    assert validate_startup_tool_calls(calls, tool_map) is None


def test_not_a_list_fails() -> None:
    tool_map = {"do_thing": _tool("do_thing")}
    assert "must contain a JSON array" in validate_startup_tool_calls({}, tool_map)


def test_entry_not_an_object_fails() -> None:
    tool_map = {"do_thing": _tool("do_thing")}
    err = validate_startup_tool_calls(["not-an-object"], tool_map)
    assert "must be an object" in err


def test_missing_name_fails() -> None:
    tool_map = {"do_thing": _tool("do_thing")}
    err = validate_startup_tool_calls([{"args": {}}], tool_map)
    assert "missing a string 'name'" in err


def test_unknown_tool_name_fails() -> None:
    tool_map = {"do_thing": _tool("do_thing")}
    err = validate_startup_tool_calls([{"name": "nope"}], tool_map)
    assert "unknown tool 'nope'" in err


def test_args_not_an_object_fails() -> None:
    tool_map = {"do_thing": _tool("do_thing")}
    err = validate_startup_tool_calls([{"name": "do_thing", "args": []}], tool_map)
    assert "'args' must be an object" in err


def test_request_unredacted_in_args_is_allowed_and_not_schema_checked() -> None:
    # startup_tool_calls.json is hand-authored by a human -- an entry IS that
    # human's approval, so request_unredacted is honored (subject to the
    # target tool's own ALLOW_REQUEST_UNREDACTED) exactly like any other
    # already-approved call, not rejected. It's also excluded from schema
    # validation (like any reserved param, it's never in a tool's own
    # DEFINITION.properties), so it doesn't trip additionalProperties: false.
    tool_map = {"do_thing": _tool("do_thing", required=["target"])}
    calls = [{"name": "do_thing", "args": {"target": "x", "request_unredacted": True}}]
    assert validate_startup_tool_calls(calls, tool_map) is None


def test_invalid_args_against_schema_fails() -> None:
    tool_map = {"do_thing": _tool("do_thing", required=["target"])}
    err = validate_startup_tool_calls([{"name": "do_thing", "args": {}}], tool_map)
    assert "invalid args" in err


def test_skill_scoped_tool_name_is_reachable() -> None:
    # Startup calls run before any skill selection, so a skill-scoped tool's
    # namespaced name must validate the same as any other, given the full
    # (base + all skills) tool map -- matching _get_session_tool_map.
    tool_map = {"web_browsing_scrape": _tool("web_browsing_scrape")}
    calls = [{"name": "web_browsing_scrape", "args": {}}]
    assert validate_startup_tool_calls(calls, tool_map) is None
