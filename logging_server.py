#!/usr/bin/env python3
"""
Simple HTTP logging server. Receives POST requests and prints the body to
stdout. Used to receive log messages from the Flask process.

Usage:
    python logging_server.py [--port PORT]

Defaults to port 8080 if --port is not supplied.
"""

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer


class _LogHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        print(body, flush=True)
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress the default per-request access log lines
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    server = HTTPServer(("localhost", args.port), _LogHandler)
    print(f"[logging_server] Listening on http://localhost:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
