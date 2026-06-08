"""Abstract base class for all news sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class RawArticle:
    """A raw article from a news source, before normalization.

    Each source produces these; the normalizer converts them to Article objects.
    """

    title: str
    url: str
    source_name: str
    default_category: str
    summary: str = ""
    published_at: Optional[datetime] = None
    extra: dict = field(default_factory=dict)  # Source-specific metadata


class Source(ABC):
    """Abstract base class for a news source.

    Each source implementation must provide:
    - name: human-readable source name
    - default_category: default category for articles from this source
    - fetch(): returns a list of RawArticle objects
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable source name."""
        ...

    @property
    @abstractmethod
    def default_category(self) -> str:
        """Default category for articles from this source."""
        ...

    @abstractmethod
    def fetch(self) -> list[RawArticle]:
        """Fetch articles from this source.

        Returns:
            List of RawArticle objects. Empty list on failure (no exceptions).
        """
        ...
