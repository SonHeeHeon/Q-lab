"""APScheduler wiring for backend batch jobs."""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.app.core.config import settings
from backend.app.services.batch.broker_order_sync import run_broker_order_sync
from backend.app.services.batch.daily_analysis import run_daily_analysis
from backend.app.services.batch.daily_report import run_daily_report
from backend.app.services.batch.data_sync import run_data_sync
from backend.app.services.batch.proposal_generator import (
    run_proposal_expiry,
    run_sleeve_proposals,
)
from backend.app.services.batch.rating_batch import run_rating_eod, run_rating_intraday
from backend.app.services.batch.record_nav_snapshot import run_nav_snapshot
from backend.app.services.batch.toss_order_sync import run_toss_order_sync

logger = logging.getLogger(__name__)


def create_batch_scheduler() -> AsyncIOScheduler:
    timezone = ZoneInfo(settings.APSCHEDULER_TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=timezone)
    scheduler.add_job(
        run_daily_analysis,
        CronTrigger.from_crontab(settings.DAILY_ANALYSIS_CRON, timezone=timezone),
        id="daily_analysis",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        kwargs={"limit": 10},
    )
    scheduler.add_job(
        run_daily_report,
        CronTrigger.from_crontab(settings.DAILY_REPORT_CRON, timezone=timezone),
        id="daily_report",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        kwargs={"limit": 10, "send_telegram": True},
    )
    scheduler.add_job(
        run_broker_order_sync,
        CronTrigger.from_crontab(settings.BROKER_ORDER_SYNC_CRON, timezone=timezone),
        id="broker_order_sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if settings.toss_credentials_configured:
        scheduler.add_job(
            run_toss_order_sync,
            CronTrigger.from_crontab(settings.TOSS_ORDER_SYNC_CRON, timezone=timezone),
            id="toss_order_sync",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    scheduler.add_job(
        run_nav_snapshot,
        CronTrigger.from_crontab(settings.NAV_SNAPSHOT_CRON, timezone=timezone),
        id="nav_snapshot",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_data_sync,
        CronTrigger.from_crontab(settings.DATA_SYNC_CRON, timezone=timezone),
        id="data_sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_sleeve_proposals,
        CronTrigger.from_crontab(settings.PROPOSAL_CRON, timezone=timezone),
        id="proposal_generation",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_proposal_expiry,
        CronTrigger.from_crontab(settings.PROPOSAL_EXPIRY_CRON, timezone=timezone),
        id="proposal_expiry",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_rating_eod,
        CronTrigger.from_crontab(settings.RATING_EOD_CRON, timezone=timezone),
        id="rating_eod",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_rating_intraday,
        CronTrigger.from_crontab(settings.RATING_INTRADAY_CRON, timezone=timezone),
        id="rating_intraday",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler


def start_batch_scheduler() -> AsyncIOScheduler:
    scheduler = create_batch_scheduler()
    scheduler.start()
    logger.info(
        "started batch scheduler: analysis=%s report=%s broker_order_sync=%s timezone=%s",
        settings.DAILY_ANALYSIS_CRON,
        settings.DAILY_REPORT_CRON,
        settings.BROKER_ORDER_SYNC_CRON,
        settings.APSCHEDULER_TIMEZONE,
    )
    return scheduler


def stop_batch_scheduler(scheduler: AsyncIOScheduler | None) -> None:
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)
