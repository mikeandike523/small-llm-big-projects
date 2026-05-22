from __future__ import annotations

from abc import ABC, abstractmethod


class RedactionPlugin(ABC):
    """Base class for redaction plugins.

    A plugin declares how well it matches a given file (by path and/or
    content), and — if selected — how to redact that content.

    The engine computes each plugin's score as:
        mean(matches_filepath(...), matches_content(...))
    and selects the highest-scoring plugin. Ties go to the first registered.

    If no plugin scores above 0.0 the content is returned unchanged.
    """

    @abstractmethod
    def matches_filepath(self, path: str | None, content: str) -> float:
        """0.0–1.0: how strongly this plugin matches based on the file path.

        Return 0.0 when path is None (not applicable) or the path pattern
        does not match. Implement content-only plugins by always returning 0.0.
        """

    @abstractmethod
    def matches_content(self, path: str | None, content: str) -> float:
        """0.0–1.0: how strongly this plugin matches based on the file content."""

    def score(self, path: str | None, content: str) -> float:
        """Combined match score: mean of filepath and content scores."""
        return (self.matches_filepath(path, content) + self.matches_content(path, content)) / 2.0

    @abstractmethod
    def redact(self, path: str | None, content: str) -> str:
        """Return the redacted content.

        May return the original string unchanged if it is determined safe.
        """
