"""Generic RSS/Atom feed fetcher."""

from datetime import datetime
from typing import Optional

import feedparser
import requests
from dateutil import parser as date_parser
from loguru import logger

from sources.base import RawArticle, Source

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class RssSource(Source):
    """Fetches articles from an RSS or Atom feed.

    Supports optional keyword filtering for feeds that cover
    broader topics beyond AI (e.g., 36Kr general tech news).
    """

    def __init__(
        self,
        name: str,
        feed_url: str,
        default_category: str = "行业动态",
        keywords: list[str] | None = None,
        max_items: int = 30,
        timeout: int = 30,
    ):
        self._name = name
        self._feed_url = feed_url
        self._default_category = default_category
        self._keywords = keywords
        self._max_items = max_items
        self._timeout = timeout

    @property
    def name(self) -> str:
        return self._name

    @property
    def default_category(self) -> str:
        return self._default_category

    def fetch(self) -> list[RawArticle]:
        articles = []
        try:
            # Use requests with User-Agent first, then feedparser for parsing
            # Some feeds (Ars Technica, The Verge) block the default feedparser UA
            resp = requests.get(
                self._feed_url,
                headers={"User-Agent": USER_AGENT},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)

            if feed.bozo:
                logger.warning(
                    f"RSS feed '{self._name}' may be malformed: {feed.bozo_exception}"
                )

            for entry in feed.entries:
                if len(articles) >= self._max_items:
                    break
                try:
                    published = self._parse_date(entry)
                    title = entry.get("title", "").strip()
                    summary = entry.get("summary", entry.get("description", ""))

                    if self._keywords:
                        text_to_match = f"{title} {summary}".lower()
                        if not any(kw.lower() in text_to_match for kw in self._keywords):
                            continue

                    articles.append(
                        RawArticle(
                            title=title,
                            url=entry.get("link", ""),
                            summary=summary,
                            source_name=self._name,
                            default_category=self._default_category,
                            published_at=published,
                        )
                    )
                except Exception as e:
                    logger.debug(f"Failed to parse entry from '{self._name}': {e}")
                    continue

            logger.info(f"RSS '{self._name}': fetched {len(articles)} articles")
        except Exception as e:
            logger.error(f"Failed to fetch RSS feed '{self._name}': {e}")

        return articles

    def _parse_date(self, entry: dict) -> Optional[datetime]:
        """Try to parse the publication date from a feed entry."""
        for field in ("published_parsed", "updated_parsed", "created_parsed"):
            time_tuple = entry.get(field)
            if time_tuple:
                try:
                    return datetime(*time_tuple[:6])
                except Exception:
                    pass

        # Fallback: try string fields
        for field in ("published", "updated", "created"):
            date_str = entry.get(field)
            if date_str:
                try:
                    return date_parser.parse(date_str)
                except Exception:
                    pass

        return datetime.now()
