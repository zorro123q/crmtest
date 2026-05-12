"""APScheduler wiring for weekly opportunity report emails."""

from __future__ import annotations

from datetime import timedelta, timezone
import logging
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.report_email_config_service import get_report_email_config
from app.services.report_email_service import send_weekly_opportunity_report

logger = logging.getLogger(__name__)

_scheduler: Any | None = None
_JOB_ID = "weekly_opportunity_report_email"


async def send_scheduled_report_job() -> None:
    try:
        config = get_report_email_config()
        if not config.get("enabled"):
            logger.info("Weekly opportunity report email is disabled in JSON config")
            return

        async with AsyncSessionLocal() as session:
            await send_weekly_opportunity_report(session)
    except Exception:
        logger.exception("Scheduled opportunity report email job failed")


def start_report_scheduler() -> None:
    global _scheduler

    if not settings.REPORT_EMAIL_ENABLED:
        logger.info("REPORT_EMAIL_ENABLED is false; opportunity report email scheduler not started")
        return

    if _scheduler is not None and getattr(_scheduler, "running", False):
        logger.info("Opportunity report email scheduler is already running")
        return

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        logger.exception("APScheduler is not installed; install apscheduler==3.10.4")
        return

    config = get_report_email_config()
    scheduler = AsyncIOScheduler(timezone=_timezone_from_config(config))
    scheduler.start()
    _scheduler = scheduler
    sync_report_scheduler()


def _timezone_from_config(config: dict[str, Any]):
    timezone_name = str(config.get("schedule_timezone") or settings.REPORT_EMAIL_TIMEZONE)
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        if timezone_name == "Asia/Shanghai":
            return timezone(timedelta(hours=8), "Asia/Shanghai")
        logger.warning("Invalid report email timezone %s, falling back to UTC", timezone_name)
        return timezone.utc


def sync_report_scheduler() -> None:
    if not settings.REPORT_EMAIL_ENABLED:
        return
    if _scheduler is None or not getattr(_scheduler, "running", False):
        return

    try:
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.exception("APScheduler is not installed; install apscheduler==3.10.4")
        return

    config = get_report_email_config()
    if not config.get("enabled"):
        existing_job = _scheduler.get_job(_JOB_ID)
        if existing_job is not None:
            existing_job.remove()
            logger.info("Opportunity report email scheduler job removed because config is disabled")
        return

    trigger = CronTrigger(
        day_of_week=config.get("schedule_weekday") or settings.REPORT_EMAIL_WEEKDAY,
        hour=config.get("schedule_hour", settings.REPORT_EMAIL_HOUR),
        minute=config.get("schedule_minute", settings.REPORT_EMAIL_MINUTE),
        timezone=_timezone_from_config(config),
    )
    _scheduler.add_job(
        send_scheduled_report_job,
        trigger=trigger,
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "Opportunity report email scheduler started: %s %02d:%02d %s",
        config.get("schedule_weekday"),
        config.get("schedule_hour"),
        config.get("schedule_minute"),
        config.get("schedule_timezone"),
    )


def shutdown_report_scheduler() -> None:
    global _scheduler

    if _scheduler is None:
        return
    try:
        if getattr(_scheduler, "running", False):
            _scheduler.shutdown(wait=False)
            logger.info("Opportunity report email scheduler stopped")
    finally:
        _scheduler = None
