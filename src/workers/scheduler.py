import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.db.session import async_session
from src.services.account_manager import AccountManager
from src.services.notifications import NotificationService
from src.services.outreach import OutreachEngine
from src.services.warmup import WarmupConveyor

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def job_warmup():
    async with async_session() as session:
        conveyor = WarmupConveyor()
        stats = await conveyor.run_daily_cycle(session)
        await session.commit()
        logger.info("Warmup job: %s", stats)


async def job_onboarding():
    async with async_session() as session:
        mgr = AccountManager()
        stats = await mgr.run_onboarding_pipeline(session)
        await session.commit()
        logger.info("Onboarding job: %s", stats)


async def job_outreach():
    async with async_session() as session:
        engine = OutreachEngine()
        stats = await engine.send_batch(session, batch_size=20)
        await session.commit()
        logger.info("Outreach job: %s", stats)


async def job_sla_check():
    async with async_session() as session:
        svc = NotificationService()
        breaches = await svc.check_sla_breaches(session)
        await session.commit()
        if breaches:
            logger.warning("SLA breaches: %d", breaches)


def start_scheduler() -> AsyncIOScheduler:
    scheduler.add_job(job_warmup, CronTrigger(hour=10, minute=0), id="warmup")
    scheduler.add_job(job_onboarding, IntervalTrigger(minutes=15), id="onboarding")
    scheduler.add_job(job_outreach, CronTrigger(hour="9-18", minute="*/30"), id="outreach")
    scheduler.add_job(job_sla_check, IntervalTrigger(minutes=15), id="sla_check")
    scheduler.start()
    logger.info("Background scheduler started")
    return scheduler
