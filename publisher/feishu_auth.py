"""Feishu (Lark) tenant access token management with caching."""

import json
import time
from pathlib import Path

import requests
from loguru import logger

FEISHU_AUTH_URL = (
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
)
TOKEN_CACHE_FILE = "data/token_cache.json"
# Refresh token when it has less than this many seconds remaining
TOKEN_SAFETY_MARGIN = 300  # 5 minutes


def get_tenant_access_token(
    app_id: str, app_secret: str, cache_path: str = TOKEN_CACHE_FILE
) -> str:
    """Get a valid tenant access token, using cache if available.

    Args:
        app_id: Feishu app ID.
        app_secret: Feishu app secret.
        cache_path: Path to the token cache file.

    Returns:
        A valid tenant access token string.

    Raises:
        RuntimeError: If unable to obtain a token after retries.
    """
    # Check cache first
    cached = _read_cache(cache_path)
    if cached:
        expires_at = cached.get("expires_at", 0)
        token = cached.get("token", "")
        if token and time.time() < expires_at - TOKEN_SAFETY_MARGIN:
            logger.debug("Using cached Feishu tenant access token")
            return token

    # Fetch new token
    return _fetch_new_token(app_id, app_secret, cache_path)


def _fetch_new_token(app_id: str, app_secret: str, cache_path: str) -> str:
    """Request a new tenant access token from Feishu."""
    for attempt in range(3):
        try:
            resp = requests.post(
                FEISHU_AUTH_URL,
                json={"app_id": app_id, "app_secret": app_secret},
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=15,
            )
            data = resp.json()
            code = data.get("code", -1)

            if code == 0:
                token = data["tenant_access_token"]
                expire = data.get("expire", 7200)  # Default 2 hours
                _write_cache(
                    cache_path,
                    token=token,
                    expires_at=time.time() + expire,
                )
                logger.info("Obtained new Feishu tenant access token")
                return token
            else:
                logger.error(
                    f"Feishu auth failed: code={code} msg={data.get('msg', '')}"
                )
                # Non-retryable errors
                if code in (10003, 10012):  # Invalid app_id or app_secret
                    raise RuntimeError(
                        f"Feishu auth error (code={code}): {data.get('msg', '')}"
                    )

        except requests.RequestException as e:
            logger.error(f"Feishu auth request failed (attempt {attempt + 1}): {e}")

        if attempt < 2:
            time.sleep(2 ** attempt)

    raise RuntimeError("Failed to get Feishu tenant access token after 3 attempts")


def _read_cache(cache_path: str) -> dict | None:
    """Read token from cache file."""
    try:
        path = Path(cache_path)
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _write_cache(cache_path: str, token: str, expires_at: float) -> None:
    """Write token to cache file."""
    try:
        path = Path(cache_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump({"token": token, "expires_at": expires_at}, f)
    except Exception as e:
        logger.warning(f"Failed to write token cache: {e}")
