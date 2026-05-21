"""
Thin coordinator — all logic lives in socket_handler_components/.

This module exists so that `import src.ui_connector.socket_handlers` (in app.py)
triggers all @socketio.on and @app.route decorator registrations, and so that
`clear_all_sessions_on_startup` remains importable from here.
"""

# noqa: F401 — side-effect imports register decorators
from src.ui_connector.socket_handler_components import http_api  # noqa: F401
from src.ui_connector.socket_handler_components import socket_events  # noqa: F401
from src.ui_connector.socket_handler_components import tool_preview  # noqa: F401
from src.ui_connector.socket_handler_components.session_store import (
    clear_all_sessions_on_startup,
)  # noqa: F401
