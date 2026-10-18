"""app/routes.py — REST API for the Twitter monitor."""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import twitter_db
from skills import twitter_image_monitor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class WatchPayload(BaseModel):
    username: str


class Status(BaseModel):
    status: str
    watches: list[str]
    total_uploads: int
    last_runs: list[dict]


@router.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok", "watches": len(twitter_db.list_watches())}


@router.get("/status")
async def status() -> Status:
    return Status(
        status="ok",
        watches=twitter_db.list_watches(),
        total_uploads=twitter_db.upload_count(),
        last_runs=twitter_db.last_run(10),
    )


@router.get("/uploads")
async def uploads(username: Optional[str] = None, limit: int = 200) -> dict:
    uploads_ = twitter_db.list_uploads(username=username, limit=limit)
    usernames = twitter_db.list_watches()
    # Per-username totals for the count summary.
    totals = {u: twitter_db.upload_count(u) for u in usernames}
    return {"uploads": uploads_, "watches": usernames, "counts": totals}


@router.get("/watch")
async def list_watches() -> dict:
    return {"watches": twitter_db.list_watches()}


@router.post("/watch")
async def add_watch(payload: WatchPayload) -> dict:
    username = payload.username.strip().lower().lstrip("@")
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    added = twitter_db.add_watch(username)
    return {"username": username, "added": added}


@router.delete("/watch/{username}")
async def remove_watch(username: str) -> dict:
    removed = twitter_db.remove_watch(username)
    if not removed:
        raise HTTPException(status_code=404, detail="watch not found")
    return {"username": username, "removed": True}


@router.post("/poll-now")
async def poll_now() -> dict:
    """Trigger an immediate monitor run. Returns the run summary."""
    summary = await twitter_image_monitor.run_and_record()
    return {"summary": summary}


@router.get("/runs")
async def runs(limit: int = 20) -> dict:
    return {"runs": twitter_db.last_run(limit)}