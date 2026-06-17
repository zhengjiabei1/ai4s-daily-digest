"""Read articles fetched by the fetch-ai4s-sources Claude Code skill.

The skill saves data/skill_fetched.json; this source reads it
so those articles are included in the daily digest pipeline.
"""

import json
from datetime import datetime
from pathlib import Path

from loguru import logger

from sources.base import RawArticle, Source

SKILL_FILE = "data/skill_fetched.json"


class SkillFeedSource(Source):
    """Reads articles pre-fetched by the Claude Code skill."""

    def __init__(self):
        pass

    @property
    def name(self) -> str:
        return "Skill Fetch (Claude Code)"

    @property
    def default_category(self) -> str:
        return "AI for Science"

    def fetch(self) -> list[RawArticle]:
        path = Path(SKILL_FILE)
        if not path.exists():
            return []

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []

            articles = []
            for item in data:
                title = (item.get("title") or "").strip()
                url = (item.get("url") or "").strip()
                if not title:
                    continue
                articles.append(RawArticle(
                    title=title,
                    url=url,
                    summary=(item.get("summary") or "").strip(),
                    source_name=item.get("source_name", self.name),
                    default_category=item.get("default_category", self.default_category),
                    published_at=None,  # no date = always passes filter
                ))

            logger.info(f"Skill Feed: loaded {len(articles)} pre-fetched articles")
            return articles
        except Exception as e:
            logger.warning(f"Skill Feed read error: {e}")
            return []
