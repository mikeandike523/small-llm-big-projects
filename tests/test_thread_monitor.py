from __future__ import annotations

import logging
import threading

from src.ui_connector.thread_monitor import ThreadMonitor, thread_group, thread_snapshot


def test_thread_group_collapses_instance_suffixes() -> None:
    assert thread_group("heartbeat-0f8e4c52-1a2b-4c3d-9e8f-001122334455") == "heartbeat"
    assert thread_group("turn-0f8e4c52-1a2b-4c3d-9e8f-001122334455") == "turn"
    assert thread_group("Thread-12 (_run)") == "Thread (_run)"
    assert thread_group("ThreadPoolExecutor-0_3") == "ThreadPoolExecutor"
    assert thread_group("MainThread") == "MainThread"


def test_snapshot_counts_live_threads() -> None:
    release = threading.Event()
    workers = [
        threading.Thread(target=release.wait, name=f"heartbeat-{i}", daemon=True)
        for i in range(3)
    ]
    for worker in workers:
        worker.start()
    try:
        snapshot = thread_snapshot()
        assert snapshot["by_group"]["heartbeat"] >= 3
        assert snapshot["total"] == len(snapshot["threads"])
    finally:
        release.set()


def test_report_warns_at_threshold(caplog) -> None:
    monitor = ThreadMonitor(warning_threshold=1)
    with caplog.at_level(logging.INFO):
        monitor.report()
    assert "Thread count: total=" in caplog.text
    assert "possible thread leak" in caplog.text
