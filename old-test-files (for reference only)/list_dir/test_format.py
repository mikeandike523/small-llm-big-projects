"""
Tests for list_dir output format: JSON structure (Mode A / Mode B), show_data
annotations, and path formatting.
"""
from __future__ import annotations

import json
import os
import sys

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

_failures: list[str] = []


def check(condition: bool, test_name: str, detail: str = "") -> None:
    if condition:
        print(f"  {PASS}  {test_name}")
    else:
        msg = f"  {FAIL}  {test_name}"
        if detail:
            msg += f"\n       detail: {detail}"
        print(msg)
        _failures.append(test_name)


def get_failures() -> list[str]:
    return _failures


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE_ROOT = os.path.join(REPO_ROOT, "scratchpad", "list_dir_test", "root")


def call_list_dir(**kwargs):
    from src.tools.list_dir import execute
    return execute(kwargs, {})


# ---------------------------------------------------------------------------
# JSON Mode A tests (filter="both")
# ---------------------------------------------------------------------------

def test_json_mode_a_structure():
    """JSON Mode A returns a single root object with nested children."""
    result = call_list_dir(path=FIXTURE_ROOT, format="json")
    data = json.loads(result)

    check(isinstance(data, dict), "json_mode_a: result is a dict", type(data).__name__)
    check(data.get("name") == "root", "json_mode_a: root name is 'root'", repr(data.get("name")))
    check(data.get("type") == "folder", "json_mode_a: root type is 'folder'", repr(data.get("type")))
    check("children" in data, "json_mode_a: root has 'children'", str(data.keys()))
    check(isinstance(data["children"], list), "json_mode_a: children is a list", type(data["children"]).__name__)


def test_json_mode_a_no_internal_fields():
    """JSON Mode A output must not contain internal fields (_loop, _is_dir_link)."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, format="json")
    # Parse and dump to catch any internal keys
    data = json.loads(result)

    def check_no_internal(node, path="root"):
        for key in node.keys():
            check(not key.startswith("_"), f"json_mode_a no internal key {key!r} at {path}", key)
        for child in node.get("children", []):
            check_no_internal(child, path + "/" + child.get("name", "?"))

    check_no_internal(data)


def test_json_mode_a_recursive_children():
    """JSON Mode A recursive listing: deeply nested children are present."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, format="json")
    data = json.loads(result)

    def find_by_name(node, name):
        if isinstance(node, dict):
            if node.get("name") == name:
                return node
            for child in node.get("children", []):
                found = find_by_name(child, name)
                if found:
                    return found
        return None

    subdir_node = find_by_name(data, "subdir")
    check(subdir_node is not None, "json_mode_a_recursive: subdir found", str(data))
    check(subdir_node.get("type") == "folder", "json_mode_a_recursive: subdir type=folder",
          str(subdir_node))
    check("children" in subdir_node, "json_mode_a_recursive: subdir has children", str(subdir_node))

    deep_node = find_by_name(data, "deep")
    check(deep_node is not None, "json_mode_a_recursive: deep found", str(data))

    very_deep = find_by_name(data, "very_deep.txt")
    check(very_deep is not None, "json_mode_a_recursive: very_deep.txt found", str(data))
    check(very_deep.get("type") == "file", "json_mode_a_recursive: very_deep.txt type=file",
          str(very_deep))


def test_json_mode_a_file_has_no_children():
    """JSON Mode A: file entries must not have a 'children' field."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, format="json")
    data = json.loads(result)

    def check_files_no_children(node, path="root"):
        if isinstance(node, dict):
            if node.get("type") == "file":
                check("children" not in node,
                      f"json_mode_a file no children: {path}/{node.get('name')}",
                      str(node))
            for child in node.get("children", []):
                check_files_no_children(child, path + "/" + node.get("name", "?"))

    check_files_no_children(data)


# ---------------------------------------------------------------------------
# JSON Mode B tests (filter="files" or "folders")
# ---------------------------------------------------------------------------

def test_json_mode_b_files_is_array():
    """JSON Mode B with filter='files' returns a flat array."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, filter="files", format="json")
    data = json.loads(result)

    check(isinstance(data, list), "json_mode_b_files: result is a list", type(data).__name__)


def test_json_mode_b_files_have_path():
    """JSON Mode B file entries have 'path' (not 'name') field."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, filter="files", format="json")
    data = json.loads(result)

    for entry in data:
        check("path" in entry, f"json_mode_b_files has path: {entry}", str(entry))
        check("name" not in entry, f"json_mode_b_files no name: {entry}", str(entry))
        check("children" not in entry, f"json_mode_b_files no children: {entry}", str(entry))


def test_json_mode_b_files_forward_slashes():
    """JSON Mode B paths use forward slashes regardless of OS."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, filter="files", format="json")
    data = json.loads(result)

    for entry in data:
        path_val = entry.get("path", "")
        check("\\" not in path_val,
              f"json_mode_b no backslash in path: {path_val!r}", path_val)


def test_json_mode_b_files_nested_paths():
    """JSON Mode B filter='files' shows paths like 'subdir/nested.txt'."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, filter="files", format="json")
    data = json.loads(result)

    paths = {e["path"] for e in data}
    check("file1.txt" in paths, "json_mode_b_files: file1.txt present", str(paths))
    check("file2.py" in paths, "json_mode_b_files: file2.py present", str(paths))
    check("subdir/nested.txt" in paths, "json_mode_b_files: subdir/nested.txt present", str(paths))
    check("subdir/deep/very_deep.txt" in paths, "json_mode_b_files: subdir/deep/very_deep.txt present",
          str(paths))


def test_json_mode_b_folders():
    """JSON Mode B filter='folders' returns only directory entries."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, filter="folders", format="json")
    data = json.loads(result)

    check(isinstance(data, list), "json_mode_b_folders: result is a list", type(data).__name__)

    paths = {e["path"] for e in data}
    check("subdir" in paths, "json_mode_b_folders: subdir present", str(paths))
    check("subdir/deep" in paths, "json_mode_b_folders: subdir/deep present", str(paths))
    check("empty_dir" in paths, "json_mode_b_folders: empty_dir present", str(paths))

    # Files must not appear
    check("file1.txt" not in paths, "json_mode_b_folders: file1.txt absent", str(paths))
    check("subdir/nested.txt" not in paths, "json_mode_b_folders: nested.txt absent", str(paths))


# ---------------------------------------------------------------------------
# Text show_data annotation tests
# ---------------------------------------------------------------------------

def test_show_data_folder_annotation():
    """show_data=True: folder entries show '(folder)' suffix."""
    result = call_list_dir(path=FIXTURE_ROOT, show_data=True)
    check("(folder)" in result, "show_data: (folder) annotation present", result[:300])
    # Root itself should show root/ (folder)
    first_line = result.splitlines()[0] if result.splitlines() else ""
    check("(folder)" in first_line, "show_data: root line contains (folder)", first_line)


def test_show_data_file_annotation():
    """show_data=True: file entries show '(file)' suffix."""
    result = call_list_dir(path=FIXTURE_ROOT, show_data=True)
    check("(file)" in result, "show_data: (file) annotation present", result[:300])


def test_show_data_false_no_annotation():
    """show_data=False (default): no parenthetical annotations."""
    result = call_list_dir(path=FIXTURE_ROOT)
    check("(file)" not in result, "show_data=false: no (file) annotation", result[:300])
    check("(folder)" not in result, "show_data=false: no (folder) annotation", result[:300])


def test_json_show_data_has_no_effect():
    """show_data has no effect when format='json' — type info always present."""
    result_sd_true = call_list_dir(path=FIXTURE_ROOT, format="json", show_data=True)
    result_sd_false = call_list_dir(path=FIXTURE_ROOT, format="json", show_data=False)
    check(result_sd_true == result_sd_false,
          "json show_data has no effect",
          f"true:\n{result_sd_true[:200]}\nfalse:\n{result_sd_false[:200]}")


# ---------------------------------------------------------------------------
# Path formatting
# ---------------------------------------------------------------------------

def test_mode_b_text_paths_use_forward_slashes():
    """Mode B text output uses forward slashes in paths."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True, filter="files")
    for line in result.splitlines():
        if line.strip():
            check("\\" not in line, f"mode_b text no backslash: {line!r}", line)


def test_mode_a_directories_have_trailing_slash():
    """Mode A text output: directory entries end with '/'."""
    result = call_list_dir(path=FIXTURE_ROOT, recursive=True)
    lines = result.splitlines()
    # Find lines whose stripped+trailing-slash-stripped name is a known directory name
    known_dirs = {"subdir", "empty_dir", "ignored_dir", "deep", "root"}
    dir_lines = []
    for l in lines:
        bare = l.split(" (")[0].rstrip()
        name = bare.strip().rstrip("/")
        if name in known_dirs:
            dir_lines.append(l)
    for l in dir_lines:
        bare = l.split(" (")[0].rstrip()
        check(bare.endswith("/"), f"mode_a dir trailing slash: {l!r}", l)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run():
    print("=== test_format.py ===")
    test_json_mode_a_structure()
    test_json_mode_a_no_internal_fields()
    test_json_mode_a_recursive_children()
    test_json_mode_a_file_has_no_children()
    test_json_mode_b_files_is_array()
    test_json_mode_b_files_have_path()
    test_json_mode_b_files_forward_slashes()
    test_json_mode_b_files_nested_paths()
    test_json_mode_b_folders()
    test_show_data_folder_annotation()
    test_show_data_file_annotation()
    test_show_data_false_no_annotation()
    test_json_show_data_has_no_effect()
    test_mode_b_text_paths_use_forward_slashes()
    test_mode_a_directories_have_trailing_slash()
    return _failures


if __name__ == "__main__":
    failures = run()
    if failures:
        print(f"\n{len(failures)} test(s) FAILED: {failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")
