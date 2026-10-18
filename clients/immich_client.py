"""
clients/immich_client.py — upload Twitter images to a self-hosted Immich server.

Feature mapping for the carve-out:
  - "twitter/{username} folder" -> Immich *album* named ``twitter/{username}``.
  - "tag the username on the photo" -> asset ``description`` is set to ``@username``
    (updated via the asset PATCH endpoint after upload).
  - URL/sha256 dedup is handled by the monitor; ``media`` (driveAssetId=sha256)
    gives Immich an additional stable dedup key.

Auth: Immich API key via ``x-api-key`` header (IMMICH_API_KEY).
Base URL: IMMICH_BASE_URL (e.g. http://immich.example:2283).
"""

import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = os.environ.get("IMMICH_BASE_URL", "http://immich:2283").rstrip("/")
DEFAULT_API_KEY = os.environ.get("IMMICH_API_KEY", "")
_DEVICE_ID = "twitter-monitor"


class ImmichClient:
    """Thin async client for the subset of the Immich REST API we need."""

    def __init__(self, base_url: str = "", api_key: str = ""):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key or DEFAULT_API_KEY
        if not self.api_key:
            logger.warning("IMMICH_API_KEY is empty — uploads will fail until it is set.")

    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "Accept": "application/json",
        }

    async def _ensure_album(self, client: httpx.AsyncClient, name: str) -> str:
        """Return the album id for ``name``, creating it if it does not exist.

        Immich has no literal folders; the ``twitter/{username}`` folder is
        modelled as an album named exactly that.
        """
        # List albums and look for an exact name match.
        resp = await client.get(f"{self.base_url}/api/albums", headers=self._headers())
        resp.raise_for_status()
        for album in resp.json():
            if album.get("albumName") == name:
                return album["id"]

        # Not found -> create.
        create = await client.post(
            f"{self.base_url}/api/albums",
            headers=self._headers(),
            json={"albumName": name},
        )
        create.raise_for_status()
        return create.json()["id"]

    async def upload_image(
        self,
        username: str,
        payload: bytes,
        signature: str,
        filename: str,
    ) -> str:
        """Upload an image into the ``twitter/{username}`` album.

        Returns the Immich asset id on success. Raises httpx.HTTPError on failure
        so the monitor can leave the image unmarked and retry next run.
        """
        async with httpx.AsyncClient(timeout=120.0) as client:
            album_id = await self._ensure_album(client, f"twitter/{username}")

            files = {
                "assetData": (filename, payload, "image/jpeg"),
            }
            data = {
                "deviceAssetId": signature,            # stable dedup key
                "deviceId": _DEVICE_ID,
                "fileCreatedAt": datetime.now(timezone.utc).isoformat(),
                "albumId": album_id,
            }
            resp = await client.post(
                f"{self.base_url}/api/assets",
                headers=self._headers(),
                data=data,
                files=files,
            )
            resp.raise_for_status()
            asset_id = resp.json().get("id")

            # Tag the username on the photo (asset description).
            patch = await client.patch(
                f"{self.base_url}/api/assets/{asset_id}",
                headers=self._headers(),
                json={"description": f"@{username}"},
            )
            # Description tagging is best-effort; a failure here shouldn't fail the run,
            # but re-raise if the *upload* itself would be ambiguous.
            if patch.status_code >= 400:
                logger.warning(
                    "Uploaded @%s asset %s but could not tag description: %s",
                    username, asset_id, patch.text[:200],
                )

            logger.info("Uploaded @%s -> immich asset %s (album twitter/%s)",
                        username, asset_id, username)
            return asset_id