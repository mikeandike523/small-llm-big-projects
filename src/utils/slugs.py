"""Folder-safe slugs for agent and user folders.

Email addresses and display names are not safe folder names: they can hold
``/``, ``?`` or ``*``, and Windows reserves names like ``CON``. A slug is always
lowercase ASCII letters, digits and hyphens, and is never a reserved name.
Uniqueness is the caller's job, using :func:`slug_candidates` and a database
unique key.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator

SLUG_MAX_CHARS = 48
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def slugify(text: str, *, fallback: str) -> str:
    """``text`` as a slug, or ``fallback`` when nothing usable remains."""
    ascii_text = (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    slug = slug[:SLUG_MAX_CHARS].rstrip("-")
    if not slug:
        return fallback
    if slug in _WINDOWS_RESERVED:
        return f"{slug}-x"
    return slug


def slug_candidates(base: str) -> Iterator[str]:
    """``base``, then ``base-2``, ``base-3``, ... for finding a free slug."""
    yield base
    number = 2
    while True:
        yield f"{base}-{number}"
        number += 1


def sender_slug_base(display_name: str | None, address: str) -> str:
    """A person's slug: from their display name, else the part before the @."""
    local_part = address.rsplit("@", 1)[0]
    return slugify(
        display_name or "",
        fallback=slugify(local_part, fallback="user"),
    )
