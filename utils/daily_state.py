"""Daily run cache: prevent re-fetching and guarantee identical output per date.

Once we push for a target date, the full card JSON is saved to a cache file.
Any re-run for the same date replays the cached card — no re-fetch, no LLM call,
guaranteeing identical output every time.  Yesterday's news is yesterday's news.
"""

import json
from datetime import date
from pathlib import Path

CACHE_FILE = "data/digest_cache.json"


def get_cached_card(target_date: date) -> dict | None:
    """Return the cached card if it exists for this date, else None."""
    cache = _read_cache()
    key = target_date.isoformat()
    return cache.get(key)


def save_card(target_date: date, card: dict) -> None:
    """Save the card to cache so re-runs on the same date are identical."""
    cache = _read_cache()
    cache[target_date.isoformat()] = card
    _write_cache(cache)


def _read_cache() -> dict:
    try:
        path = Path(CACHE_FILE)
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _write_cache(cache: dict) -> None:
    try:
        path = Path(CACHE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass
