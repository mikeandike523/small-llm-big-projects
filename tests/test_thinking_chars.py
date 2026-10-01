"""Thinking char counter: saves every 10 chunks and at the end of an exchange."""

from __future__ import annotations

import src.ui_connector.app  # noqa: F401 - server import order (avoids cycles)
from src.ui_connector.socket_handler_components import thinking_chars


def test_counter_adds_chunk_lengths_and_flushes_every_ten_chunks(monkeypatch) -> None:
    writes: list[tuple] = []
    monkeypatch.setattr(
        thinking_chars, "add_thinking_chars", lambda *args: writes.append(args)
    )
    counter = thinking_chars.ThinkingCharCounter("s1", "st1")

    for _ in range(7):
        counter.add_native(5)
    for _ in range(2):
        counter.add_irat(3)
    assert writes == []  # 9 chunks: nothing written yet
    counter.add_irat(4)
    assert writes == [("s1", "st1", 35, 10)]

    counter.add_native(2)
    counter.flush()
    counter.flush()  # nothing pending: no write
    assert writes == [("s1", "st1", 35, 10), ("s1", "st1", 2, 0)]


def test_failed_write_never_raises(monkeypatch) -> None:
    def boom(*args):
        raise RuntimeError("db down")

    monkeypatch.setattr(thinking_chars, "add_thinking_chars", boom)
    counter = thinking_chars.ThinkingCharCounter("s1", "st1")
    for _ in range(25):
        counter.add_native(8)
    counter.flush()
