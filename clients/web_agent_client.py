"""
clients/web_agent_client.py
HTTP client for the shared Twitter scraper service (webscraper).

Set TWITTER_SCRAPER_BASE_URL to point at the scraper (default: http://ser:18023).
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

TWITTER_SCRAPER_BASE_URL = os.environ.get("TWITTER_SCRAPER_BASE_URL", "http://ser:18023").rstrip("/")
_TIMEOUT = float(os.environ.get("WEB_AGENT_TIMEOUT", "60"))


async def scrape_twitter_media(username: str) -> list[str]:
    """Return pbs.twimg.com/media image URLs from a Twitter/X user's media page.

    Raises httpx.HTTPError on network or server errors.
    Returns an empty list if the account has no media.
    """
    url = f"{TWITTER_SCRAPER_BASE_URL}/scrape/twitter/media"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, json={"username": username})
        resp.raise_for_status()
        data = resp.json()

    if data.get("error"):
        logger.warning("web-agent scrape error for @%s: %s", username, data["error"])

    return data.get("images", [])


async def health_check() -> bool:
    """Return True if the Twitter scraper service is reachable and healthy."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{TWITTER_SCRAPER_BASE_URL}/health")
            return resp.status_code == 200
    except Exception:
        return False