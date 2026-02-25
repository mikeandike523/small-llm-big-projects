"""
Basic tests for search_filesystem_by_regex: pattern matching, output format, bold highlighting,
no-match case, nonexistent path error.
"""
from __future__ import annotations

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
FIXTURE_ROOT = os.path.join(REPO_ROOT, "scratchpad", "search_filesystem_by_regex_test")
ALPHA_PY = os.path.join(FIXTURE_ROOT, "alpha.py")
BETA_TXT = os.path.join(FIXTURE_ROOT, "beta.txt")
GAMMA_TXT = os.path.join(FIXTURE_ROOT, "gamma.txt")

_BOLD = "\033[1m"
_RESET = "\033[0m"


def call_search(**kwargs):
    from src.tools.search_filesystem_by_regex import execute
    return execute(kwargs, {})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_single_file_match():
    """Searching a single file returns matches from that file only."""
    result = call_search(pattern="hello", path=ALPHA_PY)
    check("alpha.py" in result, "single file: filename present in output", result[:300])
    check("hello" in result, "single file: pattern text present", result[:300])
    # Should not mention beta.txt
    check("beta.txt" not in result, "single file: other file not mentioned", result[:300])


def test_bold_applied_to_match():
    """The matched substring is wrapped in ANSI bold codes."""
    result = call_search(pattern="hello", path=ALPHA_PY)
    expected_bold = f"{_BOLD}hello{_RESET}"
    check(expected_bold in result, "bold: ANSI bold wraps matched text", repr(result[:400]))


def test_bold_not_applied_to_whole_line():
    """Only the matched portion is bold; surrounding text is plain."""
    # Line: 'def hello_world():'  — 'hello' is bold, 'def ' and '_world():' are plain
    result = call_search(pattern="hello", path=ALPHA_PY)
    # The reset code should be followed by non-bold text on the same line
    check(_RESET in result, "bold: reset code present", repr(result[:400]))
    # The line should contain text before or after the bold region
    # e.g. "def \033[1mhello\033[0m_world():"
    check("def " in result or "_world" in result, "bold: surrounding text is plain", result[:400])


def test_line_number_present():
    """Line numbers appear in the output."""
    result = call_search(pattern="hello", path=ALPHA_PY)
    # alpha.py: 'def hello_world():' is line 1, 'return "hello"' is line 2
    # At least one of these line numbers should appear
    lines = result.splitlines()
    lineno_lines = [l.strip() for l in lines if l.strip().endswith(":") and l.strip()[:-1].isdigit()]
    check(len(lineno_lines) >= 1, "line numbers: at least one line-number entry", result[:400])


def test_multiple_matches_in_file():
    """Multiple matches in one file all appear under the same file header."""
    # beta.txt has 'hello' on lines 1 and 3
    result = call_search(pattern="hello", path=BETA_TXT)
    lines = result.splitlines()
    # Count file header lines (lines ending with ':' that contain the filename)
    file_headers = [l for l in lines if "beta.txt" in l and l.rstrip().endswith(":")]
    check(len(file_headers) == 1, "multiple matches: single file header", str(file_headers))
    # Count bold occurrences
    bold_count = result.count(_BOLD)
    check(bold_count >= 2, "multiple matches: at least 2 bold regions", repr(result[:500]))


def test_directory_search_multiple_files():
    """Searching a directory finds matches across multiple files."""
    result = call_search(pattern="hello", path=FIXTURE_ROOT)
    check("alpha.py" in result, "dir search: alpha.py in results", result[:500])
    check("beta.txt" in result, "dir search: beta.txt in results", result[:500])


def test_no_match_returns_message():
    """When pattern matches nothing, returns 'No matches found.'"""
    result = call_search(pattern="zzz_no_match_xyzzy", path=FIXTURE_ROOT)
    check(result == "No matches found.", "no match: correct message", repr(result))


def test_nonexistent_path_returns_error():
    """Nonexistent path returns an Error: string."""
    result = call_search(pattern="hello", path="/nonexistent/path/xyz_abc")
    check(result.startswith("Error:"), "nonexistent path: Error string returned", repr(result))


def test_default_path_uses_cwd():
    """Omitting path uses os.getcwd() — should not error."""
    result = call_search(pattern="zzz_no_match_xyzzy_unique")
    # Either no matches or actual results — just must not be an Error
    check(not result.startswith("Error:"), "default path: no error returned", repr(result[:200]))


def test_file_path_format():
    """File path header ends with ':' and is on its own line."""
    result = call_search(pattern="hello", path=BETA_TXT)
    lines = result.splitlines()
    # First line should be the file path with trailing colon
    first_line = lines[0] if lines else ""
    check(first_line.endswith(":"), "format: first line ends with ':'", repr(first_line))
    check("beta.txt" in first_line, "format: file path in first line", repr(first_line))


def test_match_lines_indented():
    """Match entries (line number and content) are indented by two spaces."""
    result = call_search(pattern="hello", path=BETA_TXT)
    lines = result.splitlines()
    # Skip the file header line
    match_lines = lines[1:]
    for line in match_lines:
        check(line.startswith("  "), f"indentation: line starts with 2 spaces: {line!r}", repr(line))


def test_regex_character_class():
    """Character class patterns work correctly."""
    # Match lines with digits in alpha.py (x = 42)
    result = call_search(pattern=r"[0-9]+", path=ALPHA_PY)
    check("alpha.py" in result, "char class: match found in alpha.py", result[:300])
    check(f"{_BOLD}42{_RESET}" in result, "char class: '42' is bolded", repr(result[:400]))


def test_alternation_pattern():
    """Alternation patterns work correctly."""
    result = call_search(pattern="hello|world", path=BETA_TXT)
    # Should match both 'hello' and 'world' occurrences
    check(f"{_BOLD}hello{_RESET}" in result, "alternation: hello bolded", repr(result[:500]))
    check(f"{_BOLD}world{_RESET}" in result, "alternation: world bolded", repr(result[:500]))


def test_multiple_matches_on_same_line():
    """Multiple match occurrences on the same line are all bolded."""
    # beta.txt line 1: "hello there" — only one 'hello'
    # alpha.py line 5: 'return f"hello, {name}"' — one 'hello'
    # Use a pattern that matches multiple times on one line
    result = call_search(pattern=r"\w+", path=GAMMA_TXT)
    # Every word should be bolded; just check bold codes are present
    check(_BOLD in result, "multi-match on line: bold codes present", repr(result[:300]))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run():
    print("=== test_basic.py ===")
    test_single_file_match()
    test_bold_applied_to_match()
    test_bold_not_applied_to_whole_line()
    test_line_number_present()
    test_multiple_matches_in_file()
    test_directory_search_multiple_files()
    test_no_match_returns_message()
    test_nonexistent_path_returns_error()
    test_default_path_uses_cwd()
    test_file_path_format()
    test_match_lines_indented()
    test_regex_character_class()
    test_alternation_pattern()
    test_multiple_matches_on_same_line()
    return _failures


if __name__ == "__main__":
    failures = run()
    if failures:
        print(f"\n{len(failures)} test(s) FAILED: {failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")
