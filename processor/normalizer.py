"""Article normalization: converts RawArticle to a uniform Article dataclass."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from dateutil import parser as date_parser
from loguru import logger

from sources.base import RawArticle


@dataclass
class Article:
    """A normalized article ready for processing.

    All fields are populated from a RawArticle, with defaults for missing values.
    """

    title: str
    url: str
    source_name: str
    category: str  # "AI for Science" or "通用 AI" (normalized)
    summary: str = ""  # Original summary/snippet
    published_at: datetime = field(default_factory=datetime.now)
    score: float = 0.0  # Will be set by summarizer or ranker
    llm_summary: str = ""  # Chinese summary from LLM
    llm_score: int = 0  # Importance score from LLM (1-10)
    title_cn: str = ""  # Chinese title from LLM (falls back to original title)
    tag: str = ""  # Short category tag (e.g. "AI4S·材料", "通用AI·模型")
    extra: dict = field(default_factory=dict)  # Source-specific metadata

    def final_summary(self) -> str:
        """Return the best available summary."""
        return self.llm_summary or self.summary or ""

    def display_title(self) -> str:
        """Return Chinese title; if title_cn is empty or still English, fall back to llm_summary truncation."""
        cn = self.title_cn or ""
        if cn and not _is_mostly_ascii(cn):
            return cn
        if self.llm_summary:
            # Use Chinese summary as title fallback
            return self.llm_summary[:30]
        return self.title


def _is_mostly_ascii(s: str) -> bool:
    """Check if a string is mostly ASCII (likely English)."""
    ascii_chars = sum(1 for c in s if c.isascii() and c.isalpha())
    return len(s) > 0 and ascii_chars / max(len(s), 1) > 0.6


def normalize(raw_articles: list[RawArticle]) -> list[Article]:
    """Convert raw articles to normalized Article objects.

    Args:
        raw_articles: List of raw articles from sources.

    Returns:
        List of normalized Article objects.
    """
    articles = []
    for raw in raw_articles:
        try:
            article = Article(
                title=raw.title.strip(),
                url=raw.url.strip(),
                source_name=raw.source_name,
                category=raw.default_category,
                summary=_truncate(raw.summary.strip(), 500),
                published_at=raw.published_at,  # keep None as None for scrapers
                extra=raw.extra,
            )
            articles.append(article)
        except Exception as e:
            logger.debug(f"Failed to normalize article '{raw.title[:50]}': {e}")
            continue

    logger.info(f"Normalized {len(articles)} articles")
    return articles


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len characters, preserving word boundaries."""
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"
