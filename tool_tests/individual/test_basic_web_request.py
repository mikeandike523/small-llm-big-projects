from __future__ import annotations
import json
from tool_tests.helpers import CheckList
from tool_tests.helpers.env import TestEnv
from tool_tests.helpers.http_server import MicroServer
from src.tools import execute_tool

def run(env: TestEnv, server: MicroServer | None = None):
    cl = CheckList("basic_web_request")
    try:
        if server is None:
            cl.check("server available", "No MicroServer provided, skipping all checks", True, "server=None, skipping")
            return cl.result()

        # GET /hello -> 200, body contains "hello world"
        r = execute_tool("basic_web_request", {
            "url": f"{server.base_url}/hello",
            "content_type": "text/plain",
            "accept": "text/plain",
            "method": "GET",
            "timeout": 10,
        }, env.session_data)
        cl.check("GET /hello status", "Response indicates HTTP 200", "200" in r, f"got: {r!r}")
        cl.check("GET /hello body", "Response body contains 'hello world'", "hello world" in r, f"got: {r!r}")

        # GET /json -> 200, JSON response with ok=true
        r2 = execute_tool("basic_web_request", {
            "url": f"{server.base_url}/json",
            "content_type": "application/json",
            "accept": "application/json",
            "method": "GET",
            "timeout": 10,
        }, env.session_data)
        cl.check("GET /json status", "Response indicates HTTP 200", "200" in r2, f"got: {r2!r}")
        cl.check("GET /json ok field", "Response contains 'true' for ok field", "true" in r2.lower(), f"got: {r2!r}")

        # POST /echo with body "testbody" -> JSON response has body="testbody"
        r3 = execute_tool("basic_web_request", {
            "url": f"{server.base_url}/echo",
            "content_type": "application/json",
            "accept": "application/json",
            "method": "POST",
            "timeout": 10,
            "body": "testbody",
        }, env.session_data)
        cl.check("POST /echo status", "Response indicates HTTP 200", "200" in r3, f"got: {r3!r}")
        cl.check("POST /echo body echoed", "Response contains the echoed body text 'testbody'", "testbody" in r3, f"got: {r3!r}")
    except Exception as e:
        cl.record_exception(e)
    return cl.result()
