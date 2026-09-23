from __future__ import annotations

import os
import sys
import threading
from typing import Callable

_reload_lock = threading.RLock()


def reload_modules(*, tools_dir: str, session_prefix: str, load: Callable[[], object]):
    """Run a custom-tool load after evicting its modules, restoring on error."""
    tools_root = os.path.normcase(os.path.abspath(tools_dir))
    prefix = f"_slbp_{session_prefix}_"

    def belongs_to_session(name: str, module: object) -> bool:
        if name.startswith(prefix):
            return True
        module_file = getattr(module, "__file__", None)
        if not module_file:
            return False
        try:
            module_path = os.path.normcase(os.path.abspath(module_file))
            return os.path.commonpath((tools_root, module_path)) == tools_root
        except (OSError, ValueError):
            return False

    with _reload_lock:
        previous = {
            name: module
            for name, module in tuple(sys.modules.items())
            if belongs_to_session(name, module)
        }
        for name in previous:
            sys.modules.pop(name, None)
        try:
            return load()
        except Exception:
            for name, module in tuple(sys.modules.items()):
                if belongs_to_session(name, module):
                    sys.modules.pop(name, None)
            sys.modules.update(previous)
            raise
