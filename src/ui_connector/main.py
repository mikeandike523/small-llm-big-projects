"""
Entry point for the UI connector Flask/SocketIO server.

eventlet.monkey_patch() MUST be called before any other imports that touch
the standard library's socket/threading/etc so that eventlet can intercept
them.  All other project imports therefore happen after the patch.
"""

import eventlet
eventlet.monkey_patch()

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from src/ui_connector/)
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

import sys

sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.ui_connector.app import app, socketio  # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT", 5000))
    print(f"[ui_connector] Starting on port {port}")
    socketio.run(app, host="0.0.0.0", port=port)
