"""Configuration for the central tool dispatcher (src/tools/__init__.py).

Kept in its own module, separate from src/tools/config.py (built-in-tool
output constants), since this specifically configures the NextTool
delegation mechanism used by check_needs_approval/get_dirty_effects/
execute_tool -- see custom_tool_guide.md's wrapping section.
"""

from __future__ import annotations

# Maximum number of hops a single NextTool delegation chain may take before
# check_needs_approval/get_dirty_effects/execute_tool raise ToolDelegationError.
#
# There is no legitimate case for a very long chain -- delegation is not
# eager/lazy-evaluated, so a long or cyclic chain is always either a bug (an
# accidental cycle between two wrappers) or a wrapper author over-nesting
# indirection. Kept deliberately small; raise it only if a real, understood
# use case needs more hops.
MAX_TOOL_DELEGATION_HOPS = 5
