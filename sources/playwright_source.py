"""JS-rendered page fetcher using Playwright.

For Vue/React SPA sites (AISI, BAAI, etc.) where article titles
and links are only available after JavaScript execution.

Strategy: render page → extract body text → find article-like lines
→ look for corresponding hrefs in page HTML.
"""

import re
from urllib.parse import urljoin

from loguru import logger

from sources.base import RawArticle, Source

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Patterns that look like article titles (not descriptions, not navigation)
ARTICLE_LINE_PATTERN = re.compile(
    r"^(?!(登录|注册|首页|关于|联系|更多|阅读|查看|下一页|上一页|返回|Copyright|©|关注))"
    r".{10,100}$"
)
# Description-like lines to skip
DESC_PATTERNS = [
    r"^近日", r"^当前", r"^过去", r"^该\w", r"^这一", r"^为此", r"^目前",
    r"^在.{0,20}(领域|方面|背景下)", r"^\d{4}年\d{1,2}月",
    r"^[a-z]", r"^http", r"^{", r"^}$",
    r"致力于", r"成立于", r"旨在", r"推动", r"支撑",
    r"^北京\w{2,10}研究院", r"首页", r"关于我们", r"新闻动态",
    r"加入我们", r"合作伙伴", r"人才团队", r"阅读详情",
    r"Empowering Science", r"Enabling Industry",
    r"^N柱", r"^四梁", r"^平台系统", r"^亮点成果",
    r"^科研在路上",
]

TITLE_MIN_LEN = 12
TITLE_MAX_LEN = 120


class PlaywrightSource(Source):
    """Render JS page, extract article titles + links from page content."""

    def __init__(
        self,
        name: str,
        url: str,
        default_category: str = "AI for Science",
        base_url: str = "",
        max_items: int = 10,
        timeout: int = 30000,
        **kwargs,
    ):
        self._name = name
        self._url = url
        self._default_category = default_category
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
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=USER_AGENT)
                page.goto(self._url, wait_until="networkidle", timeout=self._timeout)
                page.wait_for_timeout(3000)

                body_text = page.inner_text("body")
                content_html = page.content()
                browser.close()

            # Phase 1: extract article-like lines from visible text
            candidate_titles = []
            for line in body_text.split("\n"):
                line = line.strip()
                if not (TITLE_MIN_LEN <= len(line) <= TITLE_MAX_LEN):
                    continue
                if not ARTICLE_LINE_PATTERN.match(line):
                    continue
                if any(re.search(p, line) for p in DESC_PATTERNS):
                    continue
                candidate_titles.append(line)

            # Phase 2: find URL for each title
            # Collect all <a> tags from rendered HTML
            all_links = re.findall(
                r'<(?:a|router-link)[^>]*(?:href|to)="([^"]+)"[^>]*>(.*?)</(?:a|router-link)>',
                content_html, re.DOTALL | re.IGNORECASE
            )

            for title in candidate_titles[:self._max_items * 2]:
                url = ""
                # Try exact title match first
                for href, inner in all_links:
                    inner_text = re.sub(r'<[^>]+>', '', inner).strip()
                    if inner_text[:30] == title[:30]:
                        url = urljoin(self._base_url, href)
                        break

                # Fallback: search the base URL
                if not url:
                    url = self._base_url

                articles.append(RawArticle(
                    title=title[:120],
                    url=url,
                    summary="",
                    source_name=self._name,
                    default_category=self._default_category,
                    published_at=None,  # scraper = recent
                ))

                if len(articles) >= self._max_items:
                    break

            logger.info(f"{self._name}: Playwright fetched {len(articles)} articles")
        except Exception as e:
            logger.error(f"{self._name} Playwright fetch failed: {e}")

        return articles
