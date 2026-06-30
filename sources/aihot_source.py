"""AI Hot (aihot.virxact.com) public API news source.

Provides high-quality, structured AI news with real dates,
Chinese summaries, and category tags.  No auth required.
"""

from datetime import datetime, timedelta

import requests
from loguru import logger

from sources.base import RawArticle, Source

AIHOT_URL = "https://aihot.virxact.com/api/public/items"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "aihot-quality/1.0.0"
)

# Map aihot categories to ours
CATEGORY_MAP = {
    "ai-models": "通用 AI",
    "ai-products": "通用 AI",
    "industry": "通用 AI",
    "paper": "AI for Science",
    "tip": "通用 AI",
}


class AihotSource(Source):
    """Fetches curated AI news from aihot.virxact.com."""

    def __init__(self, max_items: int = 20, timeout: int = 15):
        self._max_items = max_items
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "AI Hot"

    @property
    def default_category(self) -> str:
        return "通用 AI"

    def fetch(self) -> list[RawArticle]:
        articles = []
        try:
            since = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
            r = requests.get(
                AIHOT_URL,
                params={"mode": "selected", "since": since, "take": self._max_items},
                headers={"User-Agent": USER_AGENT},
                timeout=self._timeout,
            )
            r.raise_for_status()
            data = r.json()

            for item in data.get("items", []):
                title = (item.get("title") or "").strip()
                if not title:
                    continue

                pub_str = item.get("publishedAt") or ""
                published = None
                try:
                    published = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except Exception:
                    pass

                raw_cat = item.get("category") or ""
                our_cat = CATEGORY_MAP.get(raw_cat, "通用 AI")

                articles.append(RawArticle(
                    title=title,
                    url=item.get("url") or item.get("permalink", ""),
                    summary=item.get("summary") or "",
                    source_name=f"{self.name}({item.get('source', '')})",
                    default_category=our_cat,
                    published_at=published,
                ))

            logger.info(f"AI Hot: fetched {len(articles)} articles")
        except Exception as e:
            logger.error(f"AI Hot fetch failed: {e}")

        return articles
