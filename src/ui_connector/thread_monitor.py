"""Process thread-count tracking, for spotting thread leaks.

Logs a grouped thread count periodically (visible in the server log / desktop
Health tab), warns past a threshold, and serves an on-demand snapshot at
``GET /api/debug/threads``.
"""

from __future__ import annotations

from collections import Counter
import logging
import re
import threading

from flask import jsonify

from src.ui_connector.app import app

logger = logging.getLogger(__name__)

THREAD_MONITOR_INTERVAL_SECONDS = 300.0
THREAD_COUNT_WARNING_THRESHOLD = 150

# Strip per-instance suffixes so e.g. every "heartbeat-<session uuid>" and
# every "Thread-12 (_run)" collapse into one group each.
_INSTANCE_SUFFIX_RE = re.compile(
    r"-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|-\d+|_\d+"
)


def thread_group(name: str) -> str:
    return _INSTANCE_SUFFIX_RE.sub("", name) or name


def thread_snapshot() -> dict:
    threads = threading.enumerate()
    groups = Counter(thread_group(t.name) for t in threads)
    return {
        "total": len(threads),
        "by_group": dict(groups.most_common()),
        "threads": sorted(
            ({"name": t.name, "daemon": t.daemon} for t in threads),
            key=lambda t: t["name"],
        ),
    }


def _format_groups(by_group: dict[str, int]) -> str:
    return " ".join(f"{name}={count}" for name, count in by_group.items())


class ThreadMonitor:
    def __init__(
        self,
        *,
        interval_seconds: float = THREAD_MONITOR_INTERVAL_SECONDS,
        warning_threshold: int = THREAD_COUNT_WARNING_THRESHOLD,
    ) -> None:
        self._interval_seconds = interval_seconds
        self._warning_threshold = warning_threshold
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._peak = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="thread-monitor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def report(self) -> dict:
        snapshot = thread_snapshot()
        total = snapshot["total"]
        self._peak = max(self._peak, total)
        message = "Thread count: total=%d peak=%d [%s]"
        args = (total, self._peak, _format_groups(snapshot["by_group"]))
        if total >= self._warning_threshold:
            logger.warning(
                message + " -- at or above warning threshold %d; possible thread leak",
                *args,
                self._warning_threshold,
            )
        else:
            logger.info(message, *args)
        return snapshot

    def _loop(self) -> None:
        while True:
            try:
                self.report()
            except Exception:
                logger.exception("Thread count report failed")
            if self._stop_event.wait(self._interval_seconds):
                return


_monitor = ThreadMonitor()


def start_thread_monitor() -> None:
    _monitor.start()


def stop_thread_monitor() -> None:
    _monitor.stop()


@app.route("/api/debug/threads", methods=["GET"])
def api_debug_threads():
    return jsonify(_monitor.report())
