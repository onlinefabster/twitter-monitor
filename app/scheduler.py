"""app/scheduler.py — APScheduler wiring for the Twitter monitor loop."""

import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from skills import twitter_image_monitor

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start_monitor_scheduler() -> AsyncIOScheduler:
    """Start the cron monitor scheduler (idempotent)."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    cron = os.environ.get("MONITOR_CRON", "*/30 * * * *")
    _scheduler = AsyncIOScheduler(timezone=os.environ.get("TZ", "Europe/Amsterdam"))
    _scheduler.add_job(
        _job_run,
        CronTrigger.from_crontab(cron, timezone=os.environ.get("TZ", "Europe/Amsterdam")),
        id="twitter_monitor",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info("Twitter monitor scheduler started (%s)", cron)
    return _scheduler


async def _job_run() -> None:
    """Async job executed by APScheduler on the running event loop."""
    try:
        await twitter_image_monitor.run_and_record()
    except Exception as exc:  # never let a run crash the loop
        logger.exception("Scheduled twitter monitor run failed: %s", exc)


def shutdown_monitor_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None