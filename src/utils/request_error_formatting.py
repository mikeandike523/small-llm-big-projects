import httpx

from src.utils.context_errors import is_context_limit_error, parse_response_body
from src.utils.exceptions import ContextLimitExceededError

_SEE_LOGS = " Check debug panel logs tab for details."

_CONTEXT_LIMIT_MESSAGE = (
    "Context limit exceeded - the conversation is too long for the model's context window.\n"
    "Please start a new session or shorten the conversation."
)


def _classify_http_status_error(exc: httpx.HTTPStatusError) -> dict:
    status = exc.response.status_code
    url = str(exc.request.url) if exc.request is not None else None

    if status in (401, 403):
        reason = f"authentication/access error ({status}). Check your API token."
    elif status == 404:
        reason = "endpoint not found (404). Check your configured endpoint URL."
    elif status == 429:
        reason = "rate limited (429) by the provider."
    elif 500 <= status < 600:
        reason = f"the provider returned a server error (status {status})."
    else:
        reason = f"the provider rejected the request (status {status})."

    return {
        "gui_message": f"Request failed: {reason}{_SEE_LOGS}",
        "history_marker": f"[Request Failed - HTTP {status}]",
        "log_object": {
            "endpoint": url,
            "status": status,
            "response_body": parse_response_body(exc.response),
        },
    }


def _classify_request_error(exc: httpx.RequestError) -> dict:
    url = str(exc.request.url) if exc.request is not None else None

    if isinstance(exc, httpx.TimeoutException):
        reason = "the request to the LLM endpoint timed out"
    elif isinstance(exc, httpx.ConnectError):
        reason = "could not connect to the LLM endpoint"
    else:
        reason = "a network error occurred contacting the LLM endpoint"

    return {
        "gui_message": f"Request failed: {reason}.{_SEE_LOGS}",
        "history_marker": "[Request Failed - Network Error]",
        "log_object": {
            "endpoint": url,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        },
    }


def classify_llm_request_error(exc: Exception) -> dict:
    """Classify an exception raised while contacting the LLM into UI/history/log data.

    Returns {"gui_message": str, "history_marker": str, "log_object": dict | None}.
    """
    if isinstance(exc, ContextLimitExceededError) or is_context_limit_error(exc):
        return {
            "gui_message": (
                str(exc)
                if isinstance(exc, ContextLimitExceededError)
                else _CONTEXT_LIMIT_MESSAGE
            ),
            "history_marker": "[Context Limit Exceeded]",
            "log_object": None,
        }
    if isinstance(exc, httpx.HTTPStatusError):
        return _classify_http_status_error(exc)
    if isinstance(exc, httpx.RequestError):
        return _classify_request_error(exc)

    return {
        "gui_message": (
            f"Request failed: unexpected error contacting the LLM "
            f"({type(exc).__name__}).{_SEE_LOGS}"
        ),
        "history_marker": "[Request Failed - Unexpected Error]",
        "log_object": {
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        },
    }
