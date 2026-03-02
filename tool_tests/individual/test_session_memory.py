from __future__ import annotations
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from tool_tests.individual.session_memory import (
    checks_set,
    checks_get,
    checks_delete,
    checks_list,
    checks_append,
    checks_concat,
    checks_copy,
    checks_rename,
    checks_extract_json,
    checks_search_by_regex,
)


def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("session_memory")
    try:
        checks_set.add_checks(cl, env)
        checks_get.add_checks(cl, env)
        checks_delete.add_checks(cl, env)
        checks_list.add_checks(cl, env)
        checks_append.add_checks(cl, env)
        checks_concat.add_checks(cl, env)
        checks_copy.add_checks(cl, env)
        checks_rename.add_checks(cl, env)
        checks_extract_json.add_checks(cl, env)
        checks_search_by_regex.add_checks(cl, env)
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
