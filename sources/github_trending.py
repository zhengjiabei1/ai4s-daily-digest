"""GitHub Trending source with AI keyword filtering."""

from datetime import datetime

import requests
from bs4 import BeautifulSoup
from loguru import logger

from sources.base import RawArticle, Source

GITHUB_TRENDING_URL = "https://github.com/trending"


class GithubTrendingSource(Source):
    """Scrapes GitHub Trending page for AI-related repositories."""

    def __init__(
        self,
        languages: list[str] | None = None,
        ai_keywords: list[str] | None = None,
        timeout: int = 15,
    ):
        self._languages = languages or ["python"]
        self._ai_keywords = ai_keywords or [
            "llm", "gpt", "agent", "rag", "langchain",
            "transformer", "diffusion", "llama", "embedding", "mcp",
        ]
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "GitHub Trending"

    @property
    def default_category(self) -> str:
        return "开源工具"

    def fetch(self) -> list[RawArticle]:
        articles = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        for lang in self._languages:
            try:
                url = f"{GITHUB_TRENDING_URL}/{lang}?since=daily"
                resp = requests.get(url, headers=headers, timeout=self._timeout)
                if resp.status_code != 200:
                    logger.warning(
                        f"GitHub Trending returned {resp.status_code} for {lang}"
                    )
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                repos = soup.select("article.Box-row")

                for repo in repos:
                    try:
                        # Title and URL
                        title_link = repo.select_one("h2 a")
                        if not title_link:
                            continue
                        title = title_link.get_text(strip=True).replace("\n", " ").strip()
                        # Clean up "owner / repo" format
                        title = " ".join(title.split())

                        repo_url = "https://github.com" + title_link.get("href", "")

                        # Description
                        desc_elem = repo.select_one("p.color-fg-muted")
                        description = desc_elem.get_text(strip=True) if desc_elem else ""

                        # Stars and language
                        stars_elem = repo.select_one("span.d-inline-block.float-sm-right")
                        stars = stars_elem.get_text(strip=True) if stars_elem else ""

                        # Combine title + description for keyword matching
                        text_to_match = f"{title} {description}".lower()
                        if not any(kw in text_to_match for kw in self._ai_keywords):
                            continue

                        articles.append(
                            RawArticle(
                                title=title,
                                url=repo_url,
                                summary=description,
                                source_name=self.name,
                                default_category=self.default_category,
                                published_at=datetime.now(),
                                extra={
                                    "stars": stars,
                                    "language": lang,
                                },
                            )
                        )
                    except Exception as e:
                        logger.debug(f"Failed to parse GitHub repo: {e}")
                        continue

                logger.debug(f"GitHub Trending ({lang}): scraped {len(repos)} repos")

            except Exception as e:
                logger.error(f"Failed to fetch GitHub Trending for {lang}: {e}")

        logger.info(f"GitHub Trending: matched {len(articles)} AI-related repos")
        return articles
