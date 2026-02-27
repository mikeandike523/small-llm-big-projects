from __future__ import annotations

import os

from flask import Flask
from flask_socketio import SocketIO

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")

_cors_origin = os.environ.get("CORS_ORIGIN", "http://localhost:5173")

socketio = SocketIO(app, cors_allowed_origins=_cors_origin, async_mode="threading")

# Import handlers so their @socketio.on decorators register against the
# socketio instance created above.  Import is deferred here to avoid
# circular-import problems (handlers import `socketio` from this module).
import src.ui_connector.socket_handlers  # noqa: E402, F401
