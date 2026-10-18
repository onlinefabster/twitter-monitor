"""
app/main.py — FastAPI app for the Twitter monitor.

Hosts the control + status API, the web dashboard (static frontend), and an
APScheduler-backed monitor loop started on startup.

Run: uvicorn app.main:app --host 0.0.0.0 --port 8081
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import scheduler
from app import routes
from services import twitter_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    twitter_db.init_db()
    scheduler.start_monitor_scheduler()
    logger.info("Twitter monitor app started")
    yield
    scheduler.shutdown_monitor_scheduler()


app = FastAPI(title="Twitter Monitor", lifespan=lifespan)
app.include_router(routes.router)
app.mount("/archive", StaticFiles(directory=os.environ.get("ARCHIVE_DIR", "/app/data/archive")), name="archive")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(INDEX_FILE)