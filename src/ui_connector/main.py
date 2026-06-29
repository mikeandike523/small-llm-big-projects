"""
Entry point for the UI connector Flask/SocketIO server.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from src/ui_connector/)
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.ui_connector.app import app, socketio  # noqa: E402
from src.ui_connector.socket_handlers import (  # noqa: E402
    invalidate_redis_session_cache_on_startup,
)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


if __name__ == "__main__":
    _configure_logging()
    invalidate_redis_session_cache_on_startup()
    port = int(os.environ.get("FLASK_PORT", 5000))
    logging.getLogger("slbp.ui_connector").info("Starting on port %s", port)
    socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)
