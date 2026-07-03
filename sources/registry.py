"""Source registry: manages all sources and runs parallel fetches."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger

from sources.aihot_source import AihotSource
from sources.aisi_source import AisiSource
from sources.arxiv_source import ArxivSource
from sources.base import RawArticle, Source
from sources.baai_source import BaaiSource
from sources.github_trending import GithubTrendingSource
from sources.hacker_news import HackerNewsSource
from sources.huggingface_source import HuggingFaceSource
from sources.html_scraper import HtmlNewsSource
from sources.playwright_source import PlaywrightSource
from sources.rss_source import RssSource
from sources.skill_feed import SkillFeedSource


class SourceRegistry:
    """Manages all configured news sources and orchestrates parallel fetching."""

    def __init__(self, config: dict):
        """Initialize the registry from configuration.

        Args:
            config: Parsed configuration dictionary (from config.yaml).
        """
        self._sources: list[Source] = []
        sources_config = config.get("sources", {})

        # RSS feeds
        for feed_cfg in sources_config.get("rss_feeds", []):
            if not feed_cfg.get("enabled", True):
                continue
            self._sources.append(
                RssSource(
                    name=feed_cfg["name"],
                    feed_url=feed_cfg["url"],
                    default_category=feed_cfg.get("default_category", "行业动态"),
                    keywords=feed_cfg.get("keywords"),
                    max_items=feed_cfg.get("max_items", 30),
                )
            )

        # Hacker News
        hn_config = sources_config.get("hacker_news", {})
        if hn_config.get("enabled", True):
            self._sources.append(
                HackerNewsSource(
                    max_stories=hn_config.get("max_stories", 100),
                    keywords=hn_config.get("keywords"),
                )
            )

        # Arxiv
        arxiv_config = sources_config.get("arxiv", {})
        if arxiv_config.get("enabled", True):
            self._sources.append(
                ArxivSource(
                    categories=arxiv_config.get("categories"),
                    max_results=arxiv_config.get("max_results", 25),
                    lookback_days=arxiv_config.get("lookback_days", 2),
                )
            )

        # GitHub Trending
        github_config = sources_config.get("github_trending", {})
        if github_config.get("enabled", True):
            self._sources.append(
                GithubTrendingSource(
                    languages=github_config.get("languages", ["python"]),
                    ai_keywords=github_config.get("ai_keywords"),
                )
            )

        logger.info(f"SourceRegistry: initialized {len(self._sources)} sources")

        # ── AISI official API ──
        aisi_config = sources_config.get("aisi", {})
        if aisi_config.get("enabled", True):
            self._sources.append(AisiSource(max_items=aisi_config.get("max_items", 15)))

        # ── BAAI official API ──
        baai_config = sources_config.get("baai", {})
        if baai_config.get("enabled", True):
            self._sources.append(BaaiSource(max_items=baai_config.get("max_items", 10)))

        # ── HTML scraper for official sites without RSS ──
        for scraper_cfg in sources_config.get("scrapers", []):
            if not scraper_cfg.get("enabled", True):
                continue
            self._sources.append(HtmlNewsSource(
                name=scraper_cfg["name"],
                url=scraper_cfg["url"],
                default_category=scraper_cfg.get("default_category", "科研论文"),
                article_selector=scraper_cfg.get("article_selector", "a"),
                base_url=scraper_cfg.get("base_url", scraper_cfg["url"]),
                max_items=scraper_cfg.get("max_items", 10),
            ))

        # ── HuggingFace Daily Papers ──
        hf_config = sources_config.get("huggingface", {})
        if hf_config.get("enabled", True):
            self._sources.append(HuggingFaceSource(
                max_items=hf_config.get("max_items", 15),
            ))

        # ── AI Hot public API ──
        aihot_config = sources_config.get("aihot", {})
        if aihot_config.get("enabled", True):
            self._sources.append(AihotSource(
                max_items=aihot_config.get("max_items", 20),
            ))

        # ── Skill-fetched articles (Claude Code skill pre-fetches official pages) ──
        self._sources.append(SkillFeedSource())

        # ── Playwright JS-rendered pages ──
        for pw_cfg in sources_config.get("playwright_sources", []):
            if not pw_cfg.get("enabled", True):
                continue
            self._sources.append(PlaywrightSource(
                name=pw_cfg["name"],
                url=pw_cfg["url"],
                default_category=pw_cfg.get("default_category", "AI for Science"),
                base_url=pw_cfg.get("base_url", pw_cfg["url"]),
                max_items=pw_cfg.get("max_items", 10),
            ))

        logger.info(f"SourceRegistry: initialized {len(self._sources)} sources")

    @property
    def sources(self) -> list[Source]:
        return self._sources

    def fetch_all(self, timeout_per_source: int = 60, global_timeout: int = 180) -> list[RawArticle]:
        """Fetch articles from all sources in parallel."""
        from concurrent.futures import TimeoutError as FuturesTimeoutError

        all_articles: list[RawArticle] = []
        failed_sources: list[str] = []

        with ThreadPoolExecutor(max_workers=min(len(self._sources), 8)) as executor:
            futures = {
                executor.submit(self._fetch_source, s): s.name
                for s in self._sources
            }
            try:
                for future in as_completed(futures, timeout=global_timeout):
                    name = futures[future]
                    try:
                        articles = future.result(timeout=timeout_per_source)
                        all_articles.extend(articles)
                    except Exception as e:
                        logger.error(f"Source '{name}' failed: {e}")
                        failed_sources.append(name)
            except FuturesTimeoutError:
                # Collect unfinished sources
                for future, name in futures.items():
                    if not future.done():
                        logger.error(f"Source '{name}' timed out")
                        failed_sources.append(name)

        if failed_sources:
            logger.warning(f"{len(failed_sources)} source(s) failed: {', '.join(failed_sources)}")
        logger.info(
            f"Fetched {len(all_articles)} articles from "
            f"{len(self._sources) - len(failed_sources)}/{len(self._sources)} sources"
        )
        return all_articles

    def _fetch_source(self, source: Source) -> list[RawArticle]:
        """Fetch a single source with per-source timeout handling."""
        try:
            return source.fetch()
        except Exception as e:
            logger.error(f"Source '{source.name}' raised: {e}")
            return []
