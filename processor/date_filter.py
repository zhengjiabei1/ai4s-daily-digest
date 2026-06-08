"""Filter articles to a specific target date (e.g., yesterday)."""

from datetime import datetime, timedelta

from loguru import logger

from processor.normalizer import Article


def filter_by_date(
    articles: list[Article],
    target_date: datetime | None = None,
    days_window: int = 3,
) -> list[Article]:
    """Keep articles from a recent window around the target date.

    Many RSS feeds (Nature, MIT News, Arxiv) don't include precise
    dates, so we keep articles from the last N days plus articles
    without dates as fallback.

    Args:
        articles: Articles to filter.
        target_date: Center of the date window. Defaults to yesterday.
        days_window: Number of days to look back (inclusive).

    Returns:
        Filtered list of articles.
    """
    if target_date is None:
        target_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

    oldest = target_date - timedelta(days=days_window)
    kept = []
    no_date = []

    for article in articles:
        pub = article.published_at
        if pub is None:
            no_date.append(article)
        elif oldest.date() <= pub.date() <= target_date.date():
            kept.append(article)

    kept.extend(no_date)

    logger.info(
        f"Date filter ({oldest.date()} ~ {target_date.date()}): "
        f"kept {len(kept) - len(no_date)} with date + "
        f"{len(no_date)} without date = {len(kept)} total"
    )
    return kept
