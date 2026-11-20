from __future__ import annotations

import os
import sys
import threading
from typing import Callable

_reload_lock = threading.RLock()


def _session_module_matcher(
    tools_dir: str, session_prefix: str
) -> Callable[[str, object], bool]:
    """Return a predicate for modules owned by one session's custom tools.

    A module belongs to the session if its sys.modules key carries the
    session's ``_slbp_<prefix>_`` namespace, or its file lives under tools_dir
    (helpers pulled in via ``import_local`` or a plain ``import``).
    """
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

    return belongs_to_session


def load_discarding_partial_modules(
    *, tools_dir: str, session_prefix: str, load: Callable[[], object]
):
    """Run a custom-tool load; on error, drop every session module it added.

    A load that fails part-way would otherwise leave the modules imported
    before the failure in sys.modules, where they collide with the next load.
    Modules that were already present before this load are left alone.
    """
    belongs_to_session = _session_module_matcher(tools_dir, session_prefix)
    with _reload_lock:
        before = set(sys.modules)
        try:
            return load()
        except Exception:
            for name, module in tuple(sys.modules.items()):
                if name not in before and belongs_to_session(name, module):
                    sys.modules.pop(name, None)
            raise


def reload_modules(*, tools_dir: str, session_prefix: str, load: Callable[[], object]):
    """Run a custom-tool load after evicting its modules, restoring on error."""
    belongs_to_session = _session_module_matcher(tools_dir, session_prefix)

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
