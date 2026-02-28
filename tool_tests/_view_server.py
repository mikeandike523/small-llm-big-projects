"""Serve test_results/ with caching disabled and open in the default browser."""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from flask import Flask, make_response, send_from_directory  # noqa: E402

TEST_RESULTS_DIR = os.path.join(_REPO_ROOT, "test_results")
PORT = 9743

app = Flask(__name__)


@app.after_request
def _no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/")
def index():
    return send_from_directory(TEST_RESULTS_DIR, "index.html")


@app.route("/<path:filename>")
def static_file(filename):
    return send_from_directory(TEST_RESULTS_DIR, filename)


def _open_browser():
    time.sleep(0.9)
    webbrowser.open(f"http://localhost:{PORT}/")


if __name__ == "__main__":
    if not os.path.isdir(TEST_RESULTS_DIR):
        print("ERROR: test_results/ not found. Run ./tool_tests/run_all.sh first.")
        sys.exit(1)

    threading.Thread(target=_open_browser, daemon=True).start()
    print(f"Serving test results at http://localhost:{PORT}/")
    print("Press Ctrl+C to stop.")
    app.run(host="localhost", port=PORT, debug=False, use_reloader=False)
