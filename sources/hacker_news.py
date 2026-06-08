"""Hacker News API source with AI keyword filtering."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import requests
from loguru import logger

from sources.base import RawArticle, Source

HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"


class HackerNewsSource(Source):
    """Fetches top stories from Hacker News and filters by AI-related keywords."""

    def __init__(
        self,
        max_stories: int = 100,
        keywords: list[str] | None = None,
        lookback_hours: int = 48,
        request_timeout: int = 15,
    ):
        self._max_stories = max_stories
        self._keywords = keywords or [
            "AI", "LLM", "GPT", "Claude", "OpenAI", "Anthropic",
            "Gemini", "machine learning", "deep learning", "transformer",
        ]
        self._lookback_hours = lookback_hours
        self._timeout = 10  # faster timeout, don't block the pipeline

    @property
    def name(self) -> str:
        return "Hacker News"

    @property
    def default_category(self) -> str:
        return "行业动态"

    def fetch(self) -> list[RawArticle]:
        articles = []
        try:
            # Get top story IDs
            resp = requests.get(HN_TOP_STORIES_URL, timeout=self._timeout)
            resp.raise_for_status()
            story_ids = resp.json()[:self._max_stories]
            logger.debug(f"HN: got {len(story_ids)} top stories")

            # Fetch each story in parallel (with timeout)
            items = []
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = {
                    executor.submit(self._fetch_item, item_id): item_id
                    for item_id in story_ids
                }
                try:
                    for future in as_completed(futures, timeout=60):
                        try:
                            item = future.result(timeout=5)
                            if item:
                                items.append(item)
                        except Exception:
                            pass
                except Exception:
                    logger.debug("HN: timeout collecting stories, using what we got")

            # Filter by keywords
            cutoff = datetime.now() - timedelta(hours=self._lookback_hours)
            for item in items:
                title = item.get("title", "")
                if not self._matches_keywords(title):
                    continue

                # Check timestamp is recent
                item_time = datetime.fromtimestamp(item.get("time", 0))
                if item_time < cutoff:
                    continue

                url = item.get("url") or f"https://news.ycombinator.com/item?id={item['id']}"
                articles.append(
                    RawArticle(
                        title=title.strip(),
                        url=url,
                        source_name=self.name,
                        default_category=self.default_category,
                        published_at=item_time,
                        extra={
                            "score": item.get("score", 0),
                            "descendants": item.get("descendants", 0),
                            "hn_id": item["id"],
                        },
                    )
                )

            # Sort by score
            articles.sort(key=lambda a: a.extra.get("score", 0), reverse=True)
            logger.info(f"HN: matched {len(articles)} AI-related stories")

        except Exception as e:
            logger.error(f"Failed to fetch Hacker News: {e}")

        return articles

    def _fetch_item(self, item_id: int) -> dict | None:
        """Fetch a single HN item by ID."""
        try:
            resp = requests.get(
                HN_ITEM_URL.format(item_id=item_id), timeout=self._timeout
            )
            if resp.status_code == 200:
                item = resp.json()
                if item and item.get("type") == "story":
                    return item
        except Exception:
            pass
        return None

    def _matches_keywords(self, title: str) -> bool:
        """Check if a title contains any AI-related keyword (case-insensitive)."""
        title_lower = title.lower()
        return any(kw.lower() in title_lower for kw in self._keywords)
