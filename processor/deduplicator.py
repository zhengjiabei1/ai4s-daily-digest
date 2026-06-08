"""Article deduplication using fuzzy title matching."""

from loguru import logger
from rapidfuzz import fuzz

from processor.normalizer import Article


# Source priority (higher = keep this one when duplicates found)
SOURCE_PRIORITY = {
    "Arxiv": 10,
    "Hacker News": 8,
    "The Verge": 7,
    "TechCrunch": 7,
    "Ars Technica": 6,
    "VentureBeat": 6,
    "GitHub Trending": 5,
}

# Default priority for unlisted sources
DEFAULT_PRIORITY = 3


def deduplicate(articles: list[Article], threshold: int = 85) -> list[Article]:
    """Remove duplicate articles based on fuzzy title matching.

    Two articles are considered duplicates if their titles have a
    token_sort_ratio similarity above the threshold.

    When a duplicate is found, the article from the higher-priority
    source (or with more content) is kept.

    Args:
        articles: List of normalized articles.
        threshold: Similarity threshold (0-100). Default 85.

    Returns:
        Deduplicated list of articles.
    """
    if not articles:
        return []

    unique: list[Article] = []
    duplicates_removed = 0

    for article in articles:
        is_duplicate = False
        for i, existing in enumerate(unique):
            similarity = fuzz.token_sort_ratio(article.title, existing.title)
            if similarity >= threshold:
                is_duplicate = True
                # Keep the better article
                if _should_replace(existing, article):
                    unique[i] = article
                    logger.debug(
                        f"Dedup: replaced '{existing.title[:50]}' with "
                        f"'{article.title[:50]}' (sim={similarity})"
                    )
                duplicates_removed += 1
                break

        if not is_duplicate:
            unique.append(article)

    logger.info(
        f"Deduplication: {len(articles)} -> {len(unique)} articles "
        f"({duplicates_removed} duplicates removed, threshold={threshold})"
    )
    return unique


def _should_replace(existing: Article, new: Article) -> bool:
    """Determine if the new article should replace the existing one."""
    existing_priority = SOURCE_PRIORITY.get(existing.source_name, DEFAULT_PRIORITY)
    new_priority = SOURCE_PRIORITY.get(new.source_name, DEFAULT_PRIORITY)

    # Keep higher-priority source
    if new_priority > existing_priority:
        return True
    if new_priority < existing_priority:
        return False

    # Same priority: keep the one with more content
    return len(new.summary) > len(existing.summary)
