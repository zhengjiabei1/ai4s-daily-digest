"""HuggingFace Daily Papers API source.

https://huggingface.co/api/daily_papers — returns the latest
ML papers selected by HuggingFace community. Free, no auth.
"""

from datetime import datetime

import requests
from loguru import logger

from sources.base import RawArticle, Source

HF_API_URL = "https://huggingface.co/api/daily_papers"


class HuggingFaceSource(Source):
    """Fetches daily curated papers from HuggingFace."""

    def __init__(self, max_items: int = 20, timeout: int = 15):
        self._max_items = max_items
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "HuggingFace Papers"

    @property
    def default_category(self) -> str:
        return "AI for Science"

    def fetch(self) -> list[RawArticle]:
        articles = []
        try:
            r = requests.get(HF_API_URL, params={"limit": self._max_items},
                           headers={"User-Agent": "AISI-News-Bot/1.0"},
                           timeout=self._timeout)
            r.raise_for_status()
            data = r.json()

            for paper in data:
                title = (paper.get("title") or "").strip()
                if not title:
                    continue
                paper_id = paper.get("paper", {}).get("id", "")
                url = f"https://huggingface.co/papers/{paper_id}" if paper_id else ""
                upvotes = paper.get("paper", {}).get("upvotes", 0)

                articles.append(RawArticle(
                    title=title,
                    url=url or "https://huggingface.co/papers",
                    summary=paper.get("paper", {}).get("summary", "") or "",
                    source_name=self.name,
                    default_category=self.default_category,
                    published_at=datetime.now(),
                    extra={"upvotes": upvotes},
                ))

            logger.info(f"HuggingFace: fetched {len(articles)} papers")
        except Exception as e:
            logger.error(f"HuggingFace fetch failed: {e}")

        return articles
