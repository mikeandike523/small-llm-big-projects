from __future__ import annotations

import json
import threading

import pytest

import src.tools.search_filesystem_by_regex as search_tool
from src.tools._subprocess import SubprocessResult
from src.utils.exceptions import ToolTimeoutError


def _match_event(path: str, line: str, line_number: int) -> str:
    return json.dumps(
        {
            "type": "match",
            "data": {
                "path": {"text": path},
                "lines": {"text": line},
                "line_number": line_number,
                "submatches": [],
            },
        }
    )


def test_search_uses_rg_resolver_timeout_and_cancel_event(
    monkeypatch, tmp_path
) -> None:
    target = tmp_path / "file.txt"
    target.write_text("alpha banana omega\n", encoding="utf-8")
    cancel_event = threading.Event()
    observed: dict = {}

    def fake_resolve(command: str, args: list[str]):
        observed["command"] = command
        observed["args"] = args
        return ["resolved-rg", *args]

    def fake_run(cmd, timeout, cancel_event, cwd):
        observed.update(cmd=cmd, timeout=timeout, cancel_event=cancel_event, cwd=cwd)
        return SubprocessResult(
            returncode=0,
            stdout=_match_event(str(target), "alpha banana omega\n", 7),
            stderr="",
            success=True,
        )

    monkeypatch.setattr(search_tool, "_resolve_cmd", fake_resolve)
    monkeypatch.setattr(search_tool, "run_command", fake_run)

    result = search_tool.execute(
        {"pattern": "banana", "path": str(target), "timeout": 12},
        special_resources={"cancel_event": cancel_event},
    )

    assert observed["command"] == "rg"
    assert "--json" in observed["args"]
    assert "--no-require-git" in observed["args"]
    assert observed["timeout"] == 12
    assert observed["cancel_event"] is cancel_event
    assert "\033[1mbanana\033[0m" in result


def test_search_can_disable_ignore_rules(monkeypatch, tmp_path) -> None:
    observed: dict = {}

    def fake_resolve(command: str, args: list[str]):
        observed["args"] = args
        return [command, *args]

    monkeypatch.setattr(search_tool, "_resolve_cmd", fake_resolve)
    monkeypatch.setattr(
        search_tool,
        "run_command",
        lambda *args, **kwargs: SubprocessResult(1, "", "", False),
    )

    result = search_tool.execute(
        {"pattern": "missing", "path": str(tmp_path), "use_gitignore": False}
    )

    assert "--no-ignore" in observed["args"]
    assert "--hidden" in observed["args"]
    assert "No matches found" in result


def test_search_relabels_subprocess_timeout(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(search_tool, "_resolve_cmd", lambda _command, _args: ["rg"])

    def time_out(*_args, **_kwargs):
        raise ToolTimeoutError("rg", 3, hint="cancelled by user")

    monkeypatch.setattr(search_tool, "run_command", time_out)

    with pytest.raises(ToolTimeoutError) as caught:
        search_tool.execute({"pattern": "x", "path": str(tmp_path), "timeout": 3})

    assert caught.value.tool_name == "search_filesystem_by_regex"
    assert caught.value.hint == "cancelled by user"


def test_search_reports_missing_rg(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(search_tool, "_resolve_cmd", lambda _command, _args: ["bash"])
    monkeypatch.setattr(
        search_tool,
        "run_command",
        lambda *args, **kwargs: SubprocessResult(
            127, "", "bash: rg: command not found", False
        ),
    )

    result = search_tool.execute({"pattern": "x", "path": str(tmp_path)})

    assert "ripgrep executable 'rg' was not found" in result
