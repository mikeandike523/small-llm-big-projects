import logging


logger = logging.getLogger(__name__)

# Maximum seconds the LLM is given to respond during any single triage call.
# Applies to both Stage 1 (WAITING/INPUT classification) and Stage 1b
# (dynamic extension estimate) and Stage 2 (key injection). If the LLM
# exceeds this budget, the call is treated as failed and we fall back or kill.
HANG_DECISION_TIMEOUT = 30  # seconds

# When Stage 1 returns WAITING, Stage 1b asks the LLM how long to wait before
# checking again. Its answer is clamped to [MIN_EXTENSION_WAIT, MAX_EXTENSION_WAIT].
# If the answer is outside this range, unparseable, or the LLM call fails, we
# fall back silently to the caller-supplied hang_timeout value.
#
# MIN_EXTENSION_WAIT: shortest extension the LLM may request. Prevents the
#   watchdog from polling more aggressively than this even if the LLM says so.
# MAX_EXTENSION_WAIT: longest single extension the LLM may request. Prevents
#   indefinite deferral — but note the overall command timeout is the true hard
#   cap; extensions simply control how often we re-check.
MIN_EXTENSION_WAIT = 15   # seconds
MAX_EXTENSION_WAIT = 180  # seconds
