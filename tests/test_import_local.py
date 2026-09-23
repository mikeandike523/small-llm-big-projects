import sys
from pathlib import Path

import pytest

from src.tools import import_local


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_import_local_absolute_path(tmp_path: Path) -> None:
    helper = tmp_path / "_helpers.py"
    _write(helper, "VALUE = 42\n")
    try:
        module = import_local(str(helper))
        assert module.VALUE == 42
    finally:
        _clear_slbp_local_modules()


def test_repeated_import_returns_cached_module(tmp_path: Path) -> None:
    helper = tmp_path / "_helpers.py"
    _write(helper, "VALUE = 1\n")
    try:
        first = import_local(str(helper))
        second = import_local(str(helper))
        assert first is second
    finally:
        _clear_slbp_local_modules()


def test_same_filename_different_directories_do_not_collide(tmp_path: Path) -> None:
    dir_a = tmp_path / "plugin_a"
    dir_b = tmp_path / "plugin_b"
    _write(dir_a / "_helpers.py", "VALUE = 'a'\n")
    _write(dir_b / "_helpers.py", "VALUE = 'b'\n")
    try:
        mod_a = import_local(str(dir_a / "_helpers.py"))
        mod_b = import_local(str(dir_b / "_helpers.py"))
        assert mod_a.VALUE == "a"
        assert mod_b.VALUE == "b"
        assert mod_a is not mod_b
    finally:
        _clear_slbp_local_modules()


def test_relative_path_resolves_against_caller_directory(tmp_path: Path) -> None:
    # Simulate a "tool file" whose top-level code calls import_local with a
    # relative path -- resolved against ITS OWN __file__, not this test file's.
    caller_dir = tmp_path / "my_plugin"
    _write(caller_dir / "_helpers.py", "VALUE = 'relative'\n")
    caller_file = caller_dir / "do_thing.py"
    _write(
        caller_file,
        "from src.tools import import_local\n"
        "_helpers = import_local('_helpers.py')\n"
        "VALUE = _helpers.VALUE\n",
    )
    try:
        module = import_local(str(caller_file))
        assert module.VALUE == "relative"
    finally:
        _clear_slbp_local_modules()


def test_missing_file_raises(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.py"
    with pytest.raises((ImportError, OSError)):
        import_local(str(missing))


def _clear_slbp_local_modules() -> None:
    for name in [n for n in sys.modules if n.startswith("_slbp_local_")]:
        del sys.modules[name]
