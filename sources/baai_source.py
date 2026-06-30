"""BAAI (北京智源人工智能研究院) official news API source."""

import requests
from loguru import logger

from sources.base import RawArticle, Source

BAAI_API_URL = "https://www.baai.ac.cn/api/news"


class BaaiSource(Source):
    """Fetches news from BAAI official API."""

    def __init__(self, max_items: int = 10, timeout: int = 15):
        self._max_items = max_items
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "BAAI智源研究院"

    @property
    def default_category(self) -> str:
        return "AI for Science"

    def fetch(self) -> list[RawArticle]:
        articles = []
        try:
            resp = requests.get(BAAI_API_URL, params={"page": 1}, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])[:self._max_items]

            from datetime import datetime
            for item in items:
                title = item.get("title", "").strip()
                if not title:
                    continue
                source_url = item.get("source_url", "")
                pub_str = item.get("published_at", "")
                try:
                    published = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except Exception:
                    published = datetime.now()

                articles.append(RawArticle(
                    title=title,
                    url=source_url or f"https://www.baai.ac.cn/zh-cn/news",
                    summary=item.get("description", ""),
                    source_name=self.name,
                    default_category=self.default_category,
                    published_at=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - __import__('datetime').timedelta(days=1),  # API = yesterday
                ))
            logger.info(f"BAAI: fetched {len(articles)} articles")
        except Exception as e:
            logger.error(f"BAAI fetch failed: {e}")
        return articles
