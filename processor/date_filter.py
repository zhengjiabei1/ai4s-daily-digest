"""Filter articles to a specific target date (e.g., yesterday)."""

from datetime import datetime, timedelta

from loguru import logger

from processor.normalizer import Article


def filter_by_date(
    articles: list[Article],
    target_date: datetime | None = None,
    days_window: int = 1,
) -> list[Article]:
    """Keep only articles from the last N days.

    Articles without dates are assigned to the target date:
    scraped content runs daily, so it's from yesterday.
    """
    if target_date is None:
        target_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

    target_day = target_date.date()
    oldest = target_date - timedelta(days=days_window)
    kept = []

    for article in articles:
        pub = article.published_at
        if pub is None:
            article.published_at = target_date  # assume yesterday
            pub = target_date

        pub_date = pub.date() if hasattr(pub, "date") else pub
        if oldest.date() <= pub_date <= target_day:
            kept.append(article)

    logger.info(
        f"Date filter ({oldest.date()} ~ {target_day}): "
        f"kept {len(kept)}, dropped {len(articles) - len(kept)}"
    )
    return kept
