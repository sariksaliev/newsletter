from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    ABVariantCreate,
    AccountImport,
    AccountResponse,
    DialogMessageRequest,
    FunnelResponse,
    LeadResponse,
    LeadStatusUpdate,
    OutreachConfigCreate,
    ParseChannelRequest,
    ParseKeywordRequest,
    ProxyCreate,
)
from src.db.session import get_db
from src.models.entities import ABVariant, Account, Lead, LeadStatus, OutreachConfig
from src.services.account_manager import AccountManager
from src.services.analytics import AnalyticsService
from src.services.dialog_bot import DialogBot
from src.services.outreach import OutreachEngine
from src.services.parser import LeadParser
from src.services.proxy_manager import ProxyManager
from src.services.warmup import WarmupConveyor

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "service": "tg-outreach-platform"}


# --- Block A: Accounts & Infrastructure ---

@router.post("/proxies")
async def create_proxy(body: ProxyCreate, db: AsyncSession = Depends(get_db)):
    mgr = ProxyManager()
    proxy = await mgr.add_proxy(
        db, body.host, body.port, body.country, body.username, body.password, body.proxy_type
    )
    await db.commit()
    return {"id": proxy.id, "host": proxy.host, "country": proxy.country}


@router.post("/accounts/import", response_model=AccountResponse)
async def import_account(body: AccountImport, db: AsyncSession = Depends(get_db)):
    mgr = AccountManager()
    try:
        account = await mgr.import_account(db, body.phone, body.session_file_path, body.cost_rub)
        await db.commit()
        await db.refresh(account)
        return account
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Account).order_by(Account.id.desc()))
    return result.scalars().all()


@router.post("/accounts/onboarding/run")
async def run_onboarding(db: AsyncSession = Depends(get_db)):
    mgr = AccountManager()
    stats = await mgr.run_onboarding_pipeline(db)
    await db.commit()
    return stats


@router.post("/warmup/run")
async def run_warmup(db: AsyncSession = Depends(get_db)):
    conveyor = WarmupConveyor()
    stats = await conveyor.run_daily_cycle(db)
    await db.commit()
    return stats


@router.get("/accounts/mortality")
async def account_mortality(days: int = 30, db: AsyncSession = Depends(get_db)):
    mgr = AccountManager()
    return await mgr.get_mortality_stats(db, days)


# --- Block B: Parse & Outreach ---

@router.post("/parse/channel")
async def parse_channel(body: ParseChannelRequest, db: AsyncSession = Depends(get_db)):
    parser = LeadParser()
    try:
        job = await parser.parse_channel(db, body.channel, body.limit)
        await db.commit()
        return {"job_id": job.id, "leads_found": job.leads_found, "status": job.status}
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))


@router.post("/parse/keyword")
async def parse_keyword(body: ParseKeywordRequest, db: AsyncSession = Depends(get_db)):
    parser = LeadParser()
    try:
        job = await parser.parse_keyword_search(db, body.keyword, body.limit)
        await db.commit()
        return {"job_id": job.id, "leads_found": job.leads_found, "status": job.status}
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))


@router.get("/leads", response_model=list[LeadResponse])
async def list_leads(status: str | None = None, limit: int = 100, db: AsyncSession = Depends(get_db)):
    q = select(Lead).order_by(Lead.id.desc()).limit(limit)
    if status:
        q = q.where(Lead.status == LeadStatus(status))
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/outreach/send")
async def send_outreach(batch_size: int = 10, db: AsyncSession = Depends(get_db)):
    engine = OutreachEngine()
    stats = await engine.send_batch(db, batch_size)
    await db.commit()
    return stats


@router.get("/outreach/delivery-rate")
async def delivery_rate(days: int = 7, db: AsyncSession = Depends(get_db)):
    engine = OutreachEngine()
    return await engine.get_delivery_rate(db, days)


@router.post("/outreach/config")
async def set_outreach_config(body: OutreachConfigCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(OutreachConfig))
    for c in result.scalars().all():
        c.is_active = False
    config = OutreachConfig(**body.model_dump(), is_active=True)
    db.add(config)
    await db.commit()
    return {"id": config.id, "name": config.name}


# --- Block C: Dialog Bot ---

@router.post("/ab-variants")
async def create_ab_variant(body: ABVariantCreate, db: AsyncSession = Depends(get_db)):
    variant = ABVariant(**body.model_dump())
    db.add(variant)
    await db.commit()
    await db.refresh(variant)
    return {"id": variant.id, "name": variant.name}


@router.get("/ab-variants/stats")
async def ab_stats(db: AsyncSession = Depends(get_db)):
    bot = DialogBot()
    return await bot.get_ab_stats(db)


@router.post("/dialog/message")
async def dialog_message(body: DialogMessageRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Lead).where(Lead.id == body.lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(404, "Lead not found")
    bot = DialogBot()
    reply = await bot.handle_incoming(db, lead, body.message, body.is_voice)
    await db.commit()
    return {"reply": reply, "lead_status": lead.status.value}


@router.patch("/leads/{lead_id}/status")
async def update_lead_status(
    lead_id: int, body: LeadStatusUpdate, db: AsyncSession = Depends(get_db)
):
    bot = DialogBot()
    if body.status == "call":
        lead = await bot.mark_call(db, lead_id)
    elif body.status == "sale":
        lead = await bot.mark_sale(db, lead_id, body.sale_amount_rub or 0)
    else:
        result = await db.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()
        if lead:
            lead.status = LeadStatus(body.status)
    if not lead:
        raise HTTPException(404, "Lead not found")
    await db.commit()
    return {"id": lead.id, "status": lead.status.value}


# --- Block D: Analytics ---

@router.get("/analytics/funnel", response_model=FunnelResponse)
async def funnel_analytics(days: int = 30, db: AsyncSession = Depends(get_db)):
    svc = AnalyticsService()
    return await svc.funnel_summary(db, days)


@router.get("/analytics/daily")
async def daily_analytics(days: int = 14, db: AsyncSession = Depends(get_db)):
    svc = AnalyticsService()
    return await svc.daily_metrics(db, days)
