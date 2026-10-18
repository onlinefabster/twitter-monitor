"""
skills/twitter_image_monitor.py — Twitter/X image polling worker.

Carved out of ``onlinefabster/bot``: same URL + sha256 dedup, but images now go
to Immich (album ``twitter/{username}``) instead of Telegram, and are archived
locally to back the dashboard gallery.

Scraping stays delegated to the shared webscraper service over HTTP.
"""

import logging
import os
import hashlib
import re
from urllib.parse import urlparse
from pathlib import Path

import httpx

from services import twitter_db
from clients import web_agent_client
from clients.immich_client import ImmichClient

logger = logging.getLogger(__name__)

# How many images to upload per account per run (safety cap).
MAX_PER_ACCOUNT = int(os.environ.get("TWITTER_MAX_PER_ACCOUNT", "10"))
IMAGE_FETCH_TIMEOUT = float(os.environ.get("TWITTER_IMAGE_FETCH_TIMEOUT", "30"))
# Local archive backing the dashboard gallery: /app/data/archive/twitter/{username}/...
ARCHIVE_DIR = Path(os.environ.get("ARCHIVE_DIR", "/app/data/archive"))


def _normalize_image_url(image_url: str) -> str:
    """Normalize Twitter image URL to request the large variant consistently."""
    return re.sub(r"(name=)[^&]*", r"\1large", image_url)


async def _fetch_image_payload(
    client: httpx.AsyncClient,
    image_url: str,
) -> tuple[bytes, str] | None:
    """Fetch image bytes and return (payload, sha256), or None on failure."""
    try:
        normalized_url = _normalize_image_url(image_url)
        hasher = hashlib.sha256()
        payload = bytearray()
        async with client.stream("GET", normalized_url, follow_redirects=True) as response:
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            if content_type and not content_type.startswith("image/"):
                logger.warning("Unexpected content type for %s: %s", image_url, content_type)
                return None
            async for chunk in response.aiter_bytes():
                hasher.update(chunk)
                payload.extend(chunk)
        if not payload:
            logger.warning("Fetched empty image payload for %s", image_url)
            return None
        return bytes(payload), hasher.hexdigest()
    except Exception as exc:
        logger.warning("Failed to fetch/hash image for %s: %s", image_url, exc)
        return None


def _filename_from_url(image_url: str) -> str:
    parsed = urlparse(image_url)
    basename = os.path.basename(parsed.path) or "image"
    if "." not in basename:
        basename += ".jpg"
    return basename


def _extension_from_filename(filename: str) -> str:
    ext = Path(filename).suffix
    return ext if ext else ".jpg"


async def _archive_and_upload(
    immich: ImmichClient,
    username: str,
    image_url: str,
    payload: bytes,
    signature: str,
) -> tuple[str | None, str]:
    """Archive locally + upload to Immich.

    Returns (immich_asset_id_or_None, local_filename). The local archive is
    always written (idempotent, same file name); upload failure is surfaced by
    returning None for the asset id so the caller can retry next run.
    """
    ext = _extension_from_filename(_filename_from_url(image_url))
    local_filename = f"{signature}{ext}"
    target_dir = ARCHIVE_DIR / "twitter" / username
    target_dir.mkdir(parents=True, exist_ok=True)
    local_path = target_dir / local_filename

    if not local_path.exists():
        import aiofiles
        async with aiofiles.open(local_path, "wb") as f:
            await f.write(payload)

    try:
        asset_id = await immich.upload_image(username, payload, signature, local_filename)
    except Exception as exc:
        logger.warning("Immich upload failed for @%s %s: %s", username, image_url, exc)
        return None, local_filename

    return asset_id, local_filename


async def _run_monitor() -> tuple[str, int]:
    """Poll all watched accounts and return (summary, uploaded_count)."""
    twitter_db.init_db()

    watches = twitter_db.list_watches()
    if not watches:
        return "Twitter image monitor: no accounts on the watch list.", 0

    if not await web_agent_client.health_check():
        return (
            "Twitter image monitor: scraper service is not reachable. "
            "Make sure TWITTER_SCRAPER_BASE_URL is set correctly."
        ), 0

    immich = ImmichClient()
    total_sent = 0
    total_new = 0
    total_url_duplicates = 0
    total_signature_duplicates = 0
    total_hash_failures = 0
    results: list[str] = []

    async with httpx.AsyncClient(timeout=IMAGE_FETCH_TIMEOUT) as image_client:
        for username in watches:
            try:
                images = await web_agent_client.scrape_twitter_media(username)
            except Exception as exc:
                logger.error("Failed to scrape @%s: %s", username, exc)
                results.append(f"@{username}: scrape error — {exc}")
                continue

            unseen_urls = [url for url in images if not twitter_db.is_seen(url)]
            total_new += len(unseen_urls)
            url_duplicates = len(images) - len(unseen_urls)
            total_url_duplicates += url_duplicates
            signature_duplicates = 0
            hash_failures = 0

            to_upload: list[tuple[str, bytes, str]] = []
            for url in unseen_urls:
                if len(to_upload) >= MAX_PER_ACCOUNT:
                    break
                payload_and_signature = await _fetch_image_payload(image_client, url)
                if payload_and_signature is None:
                    hash_failures += 1
                    continue
                payload, signature = payload_and_signature
                if twitter_db.is_signature_seen(signature):
                    # Already uploaded some form of this image; only mark the URL
                    # so it is not reprocessed on later runs.
                    twitter_db.mark_seen(url, username)
                    signature_duplicates += 1
                    continue
                to_upload.append((url, payload, signature))

            uploaded_count = 0
            for url, payload, signature in to_upload:
                try:
                    asset_id, local_filename = await _archive_and_upload(
                        immich, username, url, payload, signature
                    )
                except Exception as exc:
                    logger.warning("Failed to archive/upload image from @%s: %s", username, exc)
                    continue
                if asset_id is None:
                    # Upload failed; leave unmarked so we retry next run.
                    continue
                twitter_db.mark_seen(url, username)
                twitter_db.mark_signature_seen(signature, username, url)
                twitter_db.record_upload(signature, username, url, local_filename, asset_id)
                uploaded_count += 1

            total_sent += uploaded_count
            total_signature_duplicates += signature_duplicates
            total_hash_failures += hash_failures
            results.append(
                f"@{username}: {len(images)} scraped, {len(unseen_urls)} new URL(s), "
                f"{url_duplicates} URL duplicate(s), {signature_duplicates} signature duplicate(s), "
                f"{hash_failures} fetch/hash failure(s), {uploaded_count} uploaded"
            )
            logger.info(
                "Twitter monitor @%s: %d new URLs, %d URL duplicates, %d signature duplicates, "
                "%d hash failures, %d uploaded",
                username, len(unseen_urls), url_duplicates, signature_duplicates,
                hash_failures, uploaded_count,
            )

    summary = (
        f"Twitter image monitor: {total_sent} image(s) uploaded to Immich across "
        f"{len(watches)} account(s). "
        f"Duplicates skipped: {total_url_duplicates} URL duplicate(s), "
        f"{total_signature_duplicates} signature duplicate(s). "
        f"Fetch/hash failures: {total_hash_failures}."
    )
    for r in results:
        summary += f"\n  • {r}"
    return summary, total_sent


async def run_and_record() -> str:
    """Run the monitor and persist a twitter_runs history row. Returns summary."""
    twitter_db.init_db()
    run_id = twitter_db.record_run_start()
    try:
        summary, _ = await _run_monitor()
        twitter_db.record_run_finish(run_id, "ok", summary)
    except Exception as exc:
        logger.exception("Twitter monitor run crashed")
        summary = f"Twitter image monitor crashed: {exc}"
        twitter_db.record_run_finish(run_id, "error", summary)
    return summary