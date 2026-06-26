"""Filter articles to a specific target date (e.g., yesterday)."""

from datetime import datetime, timedelta

from loguru import logger

from processor.normalizer import Article


def filter_by_date(
    articles: list[Article],
    target_date: datetime | None = None,
    days_window: int = 1,
) -> list[Article]:
    """Keep only articles published on the target date (or within window).

    Articles without dates are NOT automatically included —
    only articles with a REAL date within the window pass through.
    This prevents old scraped/API content from being treated as fresh.
    """
    if target_date is None:
        target_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

    target_day = target_date.date()
    oldest = target_date - timedelta(days=days_window)
    kept = []
    no_date = 0

    for article in articles:
        pub = article.published_at
        if pub is None:
            no_date += 1
            kept.append(article)  # scrapers run daily, content is recent
        else:
            pub_date = pub.date() if hasattr(pub, "date") else pub
            if oldest.date() <= pub_date <= target_day:
                kept.append(article)

    logger.info(
        f"Date filter ({oldest.date()} ~ {target_day}): "
        f"kept {len(kept)} (real dates), "
        f"dropped {len(articles) - len(kept)} ({no_date} undated)"
    )
    return kept
