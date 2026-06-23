"""Official news page HTML scraper — for sites without RSS/API."""

from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from loguru import logger

from sources.base import RawArticle, Source

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class HtmlNewsSource(Source):
    """Scrapes a news listing page for article links.

    Configurable selectors for different site layouts.
    """

    def __init__(
        self,
        name: str,
        url: str,
        default_category: str = "科研论文",
        article_selector: str = "a",
        title_attr: str = "text",
        link_attr: str = "href",
        base_url: str = "",
        max_items: int = 10,
        timeout: int = 15,
    ):
        self._name = name
        self._url = url
        self._default_category = default_category
        self._article_selector = article_selector
        self._title_attr = title_attr
        self._link_attr = link_attr
        self._base_url = base_url or url
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
            resp = requests.get(
                self._url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            links = soup.select(self._article_selector)
            count = 0
            for link in links:
                if count >= self._max_items:
                    break
                title = (link.get_text(strip=True) if self._title_attr == "text"
                         else link.get(self._title_attr, ""))
                if not title or len(title) < 5:
                    continue
                href = link.get(self._link_attr, "")
                if not href:
                    continue
                full_url = urljoin(self._base_url, href)

                articles.append(RawArticle(
                    title=title[:120],
                    url=full_url,
                    summary="",
                    source_name=self._name,
                    default_category=self._default_category,
                    published_at=datetime.now(),  # scraped from current page = recent
                ))
                count += 1
            logger.info(f"{self._name}: scraped {len(articles)} articles")
        except Exception as e:
            logger.error(f"{self._name} scrape failed: {e}")
        return articles
