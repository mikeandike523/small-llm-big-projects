#!/usr/bin/env python3
"""
Simple HTTP logging server. Receives POST requests and prints the body to
stdout. Used to receive log messages from the Flask/eventlet process, where
print() is unreliable due to eventlet's monkey-patching.

Listens on http://localhost:8080
"""

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
    server = HTTPServer(("localhost", 8080), _LogHandler)
    print("[logging_server] Listening on http://localhost:8080", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
