from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from tool_tests.individual.session_memory_text_editor import (
    checks_read_lines,
    checks_read_char_range,
    checks_insert_lines,
    checks_replace_lines,
    checks_delete_lines,
    checks_apply_patch,
    checks_count_chars,
    checks_count_lines,
    checks_check_eol,
    checks_normalize_eol,
    checks_check_indentation,
    checks_convert_indentation,
)


def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory_text_editor")
    try:
        checks_read_lines.add_checks(cl, env)
        checks_read_char_range.add_checks(cl, env)
        checks_insert_lines.add_checks(cl, env)
        checks_replace_lines.add_checks(cl, env)
        checks_delete_lines.add_checks(cl, env)
        checks_apply_patch.add_checks(cl, env)
        checks_count_chars.add_checks(cl, env)
        checks_count_lines.add_checks(cl, env)
        checks_check_eol.add_checks(cl, env)
        checks_normalize_eol.add_checks(cl, env)
        checks_check_indentation.add_checks(cl, env)
        checks_convert_indentation.add_checks(cl, env)
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
