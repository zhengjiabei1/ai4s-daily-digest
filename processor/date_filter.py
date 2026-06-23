"""Filter articles to a specific target date (e.g., yesterday)."""

from datetime import datetime, timedelta

from loguru import logger

from processor.normalizer import Article


def filter_by_date(
    articles: list[Article],
    target_date: datetime | None = None,
    days_window: int = 3,
) -> list[Article]:
    """Keep only articles from the last N days.

    Articles without dates are kept ONLY if we have fewer than
    10 dated articles — otherwise we assume they're stale.
    This prevents old scraped content from flooding the digest.
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

    # Articles without dates: only keep a small number as supplement
    # They're likely scraped content; don't let them dominate
    max_no_date = min(len(no_date), 5)  # at most 5 undated articles
    kept.extend(no_date[:max_no_date])

    logger.info(
        f"Date filter ({oldest.date()} ~ {target_date.date()}): "
        f"kept {len(kept)} total ({len(kept) - min(len(no_date), len(kept))} dated, "
        f"{min(len(no_date), len(kept))} no-date), "
        f"dropped {len(articles) - len(kept)} old/undated"
    )
    return kept
