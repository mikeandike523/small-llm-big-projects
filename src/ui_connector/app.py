from __future__ import annotations

import os

from flask import Flask, request, make_response
from flask_socketio import SocketIO

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")

socketio = SocketIO(
    app, cors_allowed_origins="*", async_mode="threading", path="api/socket.io"
)


@app.after_request
def _add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = (
        "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    )
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


@app.before_request
def _handle_preflight():
    if request.method == "OPTIONS":
        resp = make_response()
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = (
            "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        )
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.status_code = 204
        return resp


# Import handlers so their @socketio.on decorators register against the
# socketio instance created above.  Import is deferred here to avoid
# circular-import problems (handlers import `socketio` from this module).
import src.ui_connector.socket_handlers  # noqa: E402, F401
import src.config_routes.tokens  # noqa: E402, F401
