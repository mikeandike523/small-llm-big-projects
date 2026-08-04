import pytest

from run_tool import parse_tool_cli_args


def test_string_and_integer_args_are_coerced_from_raw_strings() -> None:
    args = parse_tool_cli_args("list_dir", ["--path", "src", "--depth", "2"])

    assert args["path"] == "src"
    assert args["depth"] == 2


def test_boolean_args_support_bare_flags_and_explicit_values() -> None:
    bare = parse_tool_cli_args("list_dir", ["--recursive"])
    explicit = parse_tool_cli_args(
        "code_interpreter",
        ["--raw_code", "print('x')", "--enable_tracebacks", "false"],
    )

    assert bare["recursive"] is True
    assert explicit["enable_tracebacks"] is False


def test_array_args_collect_repeated_flags() -> None:
    args = parse_tool_cli_args(
        "host_shell",
        ["--command", "git", "--command_args", "status", "--command_args=--short"],
    )

    assert args == {"command": "git", "command_args": ["status", "--short"]}


def test_string_map_object_args_accept_repeated_key_value_entries() -> None:
    args = parse_tool_cli_args(
        "basic_web_request",
        [
            "--url",
            "https://example.com",
            "--method",
            "GET",
            "--timeout",
            "10",
            "--headers",
            "Accept=application/json",
            "--headers",
            "Authorization=Bearer token",
        ],
    )

    assert args["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer token",
    }


def test_missing_required_args_error() -> None:
    with pytest.raises(ValueError, match="missing required args: url, method"):
        parse_tool_cli_args("basic_web_request", [])


def test_extra_args_error() -> None:
    with pytest.raises(ValueError, match="unexpected args: nope"):
        parse_tool_cli_args("list_dir", ["--nope", "x"])


def test_non_array_arg_cannot_repeat() -> None:
    with pytest.raises(ValueError, match="--path may not be provided more than once"):
        parse_tool_cli_args("list_dir", ["--path", "src", "--path", "tests"])
