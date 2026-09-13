import inspect

from src.tools import _TOOL_MAP


def test_builtin_needs_approval_hooks_accept_framework_context() -> None:
    expected = ["args", "session_data", "special_resources"]

    for name, module in _TOOL_MAP.items():
        fn = getattr(module, "needs_approval", None)
        if fn is None:
            continue

        params = list(inspect.signature(fn).parameters.values())
        assert [p.name for p in params[:3]] == expected, name
        assert params[1].default is None, name
        assert params[2].default is None, name
