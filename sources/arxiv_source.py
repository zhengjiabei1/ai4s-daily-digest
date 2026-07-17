"""Arxiv API source for latest AI/ML research papers."""

from datetime import datetime, timedelta

import feedparser
from dateutil import parser as date_parser
from loguru import logger

from sources.base import RawArticle, Source

ARXIV_API_URL = "http://export.arxiv.org/api/query"


class ArxivSource(Source):
    """Fetches recent papers from Arxiv in AI/ML categories."""

    CATEGORY_LABELS = {
        "cs.AI": "人工智能",
        "cs.CL": "自然语言处理",
        "cs.LG": "机器学习",
        "cs.CV": "计算机视觉",
    }

    def __init__(
        self,
        categories: list[str] | None = None,
        max_results: int = 25,
        lookback_days: int = 2,
        timeout: int = 30,
    ):
        self._categories = categories or ["cs.AI", "cs.CL", "cs.LG", "cs.CV"]
        self._max_results = max_results
        self._lookback_days = lookback_days
        self._timeout = 20  # shorter timeout

    @property
    def name(self) -> str:
        return "Arxiv"

    @property
    def default_category(self) -> str:
        return "科研论文"

    def fetch(self) -> list[RawArticle]:
        articles = []
        try:
            # Build the search query: cat:cs.AI OR cat:cs.CL OR ...
            cat_query = "+OR+".join(f"cat:{cat}" for cat in self._categories)
            url = (
                f"{ARXIV_API_URL}?search_query={cat_query}"
                f"&sortBy=submittedDate&sortOrder=descending"
                f"&max_results={self._max_results}"
            )

            feed = feedparser.parse(url)

            # Diagnose empty responses
            if not feed.entries:
                status = getattr(feed, "status", None)
                bozo = getattr(feed, "bozo_exception", None)
                logger.warning(
                    f"Arxiv API returned 0 entries (status={status}, "
                    f"bozo={str(bozo)[:120] if bozo else 'None'})"
                )
                return articles

            cutoff = datetime.now() - timedelta(days=self._lookback_days)

            for entry in feed.entries:
                try:
                    published = self._parse_date(entry)
                    if published and published.replace(tzinfo=None) < cutoff:
                        continue

                    # Extract arxiv ID from the URL
                    arxiv_id = entry.get("id", "").split("/abs/")[-1]
                    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"

                    # Get primary category
                    primary_cat = entry.get("arxiv_primary_category", {})
                    cat_code = primary_cat.get("term", "") if isinstance(primary_cat, dict) else ""
                    cat_label = self.CATEGORY_LABELS.get(cat_code, "科研论文")

                    # Extract authors
                    authors = [a.get("name", "") for a in entry.get("authors", [])]

                    articles.append(
                        RawArticle(
                            title=entry.get("title", "").strip().replace("\n", " "),
                            url=entry.get("link", pdf_url),
                            summary=entry.get("summary", "").strip().replace("\n", " "),
                            source_name=f"Arxiv ({cat_label})",
                            default_category=f"科研论文 - {cat_label}",
                            published_at=published,
                            extra={
                                "authors": authors,
                                "arxiv_id": arxiv_id,
                                "pdf_url": pdf_url,
                                "primary_category": cat_code,
                            },
                        )
                    )
                except Exception as e:
                    logger.debug(f"Failed to parse Arxiv entry: {e}")
                    continue

            logger.info(f"Arxiv: fetched {len(articles)} recent papers")

        except Exception as e:
            logger.error(f"Failed to fetch Arxiv: {e}")

        return articles

    def _parse_date(self, entry: dict) -> datetime | None:
        for date_field in ("published", "updated"):
            date_str = entry.get(date_field)
            if date_str:
                try:
                    return date_parser.parse(date_str)
                except Exception:
                    pass
        return None
