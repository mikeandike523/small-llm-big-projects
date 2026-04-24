"""Tiny HTTP server used as subprocess target for basic_web_request tests."""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        # Suppress all access logs
        pass

    def _send(self, status: int, content_type: str, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == "/hello":
            self._send(200, "text/plain", "hello world")
        elif self.path == "/json":
            self._send(200, "application/json", json.dumps({"ok": True}))
        elif self.path == "/article":
            self._send(
                200,
                "text/html; charset=utf-8",
                """<!doctype html>
<html>
  <head><title>Example Article</title></head>
  <body>
    <main>
      <h1>Example Article</h1>
      <p>This page exists to exercise readable extraction.</p>
      <p><a href="https://example.com/ref">Reference Link</a></p>
    </main>
  </body>
</html>""",
            )
        else:
            self._send(404, "text/plain", "not found")

    def do_POST(self):
        if self.path == "/echo":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            self._send(200, "application/json", json.dumps({"method": "POST", "body": body}))
        else:
            self._send(404, "text/plain", "not found")


if __name__ == "__main__":
    port = int(sys.argv[1])
    server = HTTPServer(("127.0.0.1", port), _Handler)
    server.serve_forever()
