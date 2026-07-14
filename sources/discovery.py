"""Active Discovery Engine — searches for high-quality news beyond RSS sources.

Uses quality templates to generate targeted search queries,
fetches results from DuckDuckGo web search, and returns them as RawArticle objects.
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, unquote, parse_qs, urlparse

import requests
from loguru import logger

from sources.base import RawArticle, Source

TEMPLATES_FILE = Path("data/quality_templates.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _extract_real_url(ddg_url: str) -> str:
    """Extract the real URL from DuckDuckGo's redirect wrapper."""
    if "uddg=" in ddg_url:
        parsed = urlparse(ddg_url)
        qs = parse_qs(parsed.query)
        real = qs.get("uddg", [ddg_url])[0]
        return unquote(real)
    return ddg_url


class DiscoverySource(Source):
    """Actively searches for high-quality AI news using web search."""

    def __init__(
        self,
        max_queries: int = 20,
        results_per_query: int = 5,
        max_items: int = 50,
        timeout: int = 15,
    ):
        self._max_queries = max_queries
        self._results_per_query = results_per_query
        self._max_items = max_items
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "Active Discovery"

    @property
    def default_category(self) -> str:
        return "通用 AI"

    def fetch(self) -> list[RawArticle]:
        articles = []
        templates = _load_templates()
        queries = _generate_queries(templates, self._max_queries)

        logger.info(f"Discovery: searching {len(queries)} queries...")
        yesterday = datetime.now() - timedelta(days=1)
        yesterday_str = yesterday.strftime("%Y-%m-%d")

        seen_urls = set()
        for q in queries[:self._max_queries]:
            try:
                results = _search_duckduckgo(q, self._results_per_query, self._timeout)
                for result in results:
                    url = result.get("url", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)

                    title = (result.get("title") or "").strip()
                    if not title or len(title) < 8:
                        continue

                    articles.append(RawArticle(
                        title=title[:120],
                        url=_extract_real_url(url),
                        summary=result.get("snippet", "")[:300],
                        source_name=f"Discovery ({result.get('source', 'web')})",
                        default_category="AI for Science",  # default, LLM will re-classify
                        published_at=yesterday,
                        extra={"search_query": q},
                    ))

                    if len(articles) >= self._max_items:
                        break
            except Exception as e:
                logger.debug(f"Discovery search failed for '{q}': {e}")
                continue

            if len(articles) >= self._max_items:
                break

        logger.info(f"Discovery: found {len(articles)} articles from web search")
        return articles


# ── Template management ──────────────────────────────────────────────

def _load_templates() -> dict:
    if TEMPLATES_FILE.exists():
        try:
            return json.loads(TEMPLATES_FILE.read_text())
        except Exception:
            pass
    return {"topics": [], "search_domains": [], "search_templates": []}


def _generate_queries(templates: dict, max_count: int) -> list[str]:
    """Generate search queries from templates. Combines topics with domains
    and templates for wide coverage of high-quality news sources."""
    queries = []

    # 1. Domain-specific searches (highest priority - government/research sites)
    domains = templates.get("search_domains", [])[:10]
    for domain in domains[:8]:
        domain_name = domain.replace("www.", "").split(".")[0]
        queries.append(f"AI OR 人工智能 OR 大模型 site:{domain}")
        queries.append(f"人工智能 政策 OR 发布 OR 突破 site:{domain}")

    # 2. Topic-based searches
    topics = templates.get("topics", [])[:15]
    for topic in random.sample(topics, min(len(topics), 10)):
        queries.append(f"{topic} 最新")
        queries.append(f"{topic} 2026")

    # 3. News-focused searches for yesterday
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    date_str = yesterday.strftime("%Y-%m-%d")
    queries.append(f"AI for Science {date_str}")
    queries.append(f"人工智能 {date_str}")
    queries.append(f"大模型 发布 {date_str}")

    # Shuffle and limit
    random.shuffle(queries)
    return queries[:max_count]


# ── Web search ───────────────────────────────────────────────────────

def _search_duckduckgo(query: str, max_results: int, timeout: int) -> list[dict]:
    """Search DuckDuckGo and return results."""
    results = []
    try:
        # Use DuckDuckGo lite (no JS, lightweight HTML)
        url = f"https://lite.duckduckgo.com/lite/?q={quote(query)}"
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return results

        # Parse the simple lite HTML
        from html.parser import HTMLParser

        class LiteParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.results = []
                self.current = {}
                self.in_link = False
                self.in_snippet = False
                self.link_url = ""
                self.buffer = ""

            def handle_starttag(self, tag, attrs):
                attrs_dict = dict(attrs)
                if tag == "a" and "href" in attrs_dict:
                    href = attrs_dict["href"]
                    if href.startswith("//"):
                        href = "https:" + href
                    self.link_url = href
                    self.in_link = True
                    self.buffer = ""
                elif tag == "td" and "result-snippet" in attrs_dict.get("class", ""):
                    self.in_snippet = True
                    self.buffer = ""

            def handle_endtag(self, tag):
                if tag == "a" and self.in_link:
                    self.in_link = False
                    title = self.buffer.strip()
                    if title and self.link_url:
                        self.current = {"title": title, "url": self.link_url}
                elif tag == "td" and self.in_snippet:
                    self.in_snippet = False
                    self.current["snippet"] = self.buffer.strip()
                    if self.current.get("title"):
                        self.results.append(self.current)
                    self.current = {}

            def handle_data(self, data):
                if self.in_link or self.in_snippet:
                    self.buffer += data

        parser = LiteParser()
        parser.feed(resp.text)
        results = parser.results[:max_results]

    except Exception as e:
        logger.debug(f"DuckDuckGo search error: {e}")

    return results
