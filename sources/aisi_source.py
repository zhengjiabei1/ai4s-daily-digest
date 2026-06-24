"""AISI (北京科学智能研究院) official article API source.

API: https://www.aisi.ac.cn/api/article/lists?is_cn=1&page=1&limit=999
Returns all Chinese articles with title, content, create_time.
"""

import re
from datetime import datetime

import requests
from loguru import logger

from sources.base import RawArticle, Source

AISI_API_URL = "https://www.aisi.ac.cn/api/article/lists"


class AisiSource(Source):
    """Fetches AISI news articles via the official JSON API."""

    def __init__(self, max_items: int = 15, timeout: int = 15):
        self._max_items = max_items
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "AISI 北京科学智能研究院"

    @property
    def default_category(self) -> str:
        return "AI for Science"

    def fetch(self) -> list[RawArticle]:
        articles = []
        try:
            resp = requests.get(
                AISI_API_URL,
                params={"is_cn": 1, "page": 1, "limit": self._max_items},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                logger.error(f"AISI API error: {data.get('msg')}")
                return []

            items = data.get("data", {}).get("data", [])
            for item in items:
                title = (item.get("title") or "").strip()
                if not title:
                    continue

                # Extract first paragraph as summary from HTML content
                html_content = item.get("content", "")
                summary = _extract_paragraph(html_content)

                # Parse date
                pub_str = item.get("create_time", "")
                try:
                    published = datetime.strptime(pub_str, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    published = None

                article_id = item.get("id", "")
                url = f"https://www.aisi.ac.cn/#/news/article/{article_id}" if article_id else "https://www.aisi.ac.cn/"

                articles.append(RawArticle(
                    title=title,
                    url=url,
                    summary=summary,
                    source_name=self.name,
                    default_category=self.default_category,
                    published_at=None,  # cached content, treat as recent
                ))

            logger.info(f"AISI: fetched {len(articles)} articles")
        except Exception as e:
            logger.error(f"AISI fetch failed: {e}")

        return articles


def _extract_paragraph(html: str) -> str:
    """Extract first meaningful paragraph from HTML content."""
    # Strip all HTML tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Take first 200 chars
    if len(text) > 200:
        text = text[:200] + "…"
    return text
