from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.entities import (
    Account,
    AccountStatus,
    DeliveryStatus,
    FunnelEvent,
    Lead,
    LeadStatus,
    OutreachMessage,
)


class AnalyticsService:
    """End-to-end funnel analytics with CPL/CAC per step."""

    async def funnel_summary(self, session: AsyncSession, days: int = 30) -> dict:
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

        leads_total = await self._count_leads(session, since)
        written = await self._count_by_status(session, LeadStatus.WRITTEN, since, gte=True)
        replied = await self._count_by_status(session, LeadStatus.REPLIED, since, gte=True)
        in_bot = await self._count_by_status(session, LeadStatus.IN_BOT, since, gte=True)
        applications = await self._count_by_status(session, LeadStatus.APPLICATION, since, gte=True)
        calls = await self._count_by_status(session, LeadStatus.CALL, since, gte=True)
        sales = await self._count_by_status(session, LeadStatus.SALE, since, gte=True)

        delivery = await self._delivery_stats(session, since)
        total_cost = await self._total_cost(session, since)

        cpl = round(total_cost / max(applications, 1), 2)
        cac = round(total_cost / max(sales, 1), 2)

        return {
            "period_days": days,
            "funnel": {
                "reach": leads_total,
                "written": written,
                "delivered": delivery["delivered"],
                "delivery_pct": delivery["delivery_pct"],
                "replied": replied,
                "reply_pct": round(replied / max(delivery["delivered"], 1) * 100, 1),
                "in_bot": in_bot,
                "applications": applications,
                "app_pct": round(applications / max(replied, 1) * 100, 1),
                "calls": calls,
                "sales": sales,
                "sale_pct": round(sales / max(applications, 1) * 100, 1),
            },
            "economics": {
                "total_cost_rub": round(total_cost, 2),
                "cost_per_message_rub": round(total_cost / max(delivery["total"], 1), 2),
                "cpl_rub": cpl,
                "cac_rub": cac,
                "revenue_rub": await self._revenue(session, since),
            },
            "accounts": await self._account_health(session, days),
        }

    async def _count_leads(self, session: AsyncSession, since: datetime) -> int:
        result = await session.execute(
            select(func.count(Lead.id)).where(Lead.created_at >= since)
        )
        return result.scalar() or 0

    async def _count_by_status(
        self, session: AsyncSession, status: LeadStatus, since: datetime, gte: bool = False
    ) -> int:
        statuses = list(LeadStatus)
        idx = statuses.index(status)
        target_statuses = statuses[idx:]
        result = await session.execute(
            select(func.count(Lead.id)).where(
                Lead.created_at >= since,
                Lead.status.in_(target_statuses),
            )
        )
        return result.scalar() or 0

    async def _delivery_stats(self, session: AsyncSession, since: datetime) -> dict:
        result = await session.execute(
            select(OutreachMessage).where(OutreachMessage.created_at >= since)
        )
        messages = result.scalars().all()
        total = len(messages)
        delivered = sum(1 for m in messages if m.delivery_status == DeliveryStatus.DELIVERED)
        return {
            "total": total,
            "delivered": delivered,
            "delivery_pct": round(delivered / max(total, 1) * 100, 1),
        }

    async def _total_cost(self, session: AsyncSession, since: datetime) -> float:
        events = await session.execute(
            select(func.sum(FunnelEvent.cost_rub)).where(FunnelEvent.created_at >= since)
        )
        event_cost = events.scalar() or 0.0

        accounts = await session.execute(select(Account))
        account_cost = sum(a.cost_rub for a in accounts.scalars().all() if a.created_at >= since)
        return float(event_cost) + float(account_cost)

    async def _revenue(self, session: AsyncSession, since: datetime) -> float:
        result = await session.execute(
            select(func.sum(Lead.sale_amount_rub)).where(
                Lead.sale_at >= since,
                Lead.status == LeadStatus.SALE,
            )
        )
        return float(result.scalar() or 0.0)

    async def _account_health(self, session: AsyncSession, days: int) -> dict:
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        result = await session.execute(select(Account))
        accounts = result.scalars().all()
        recent = [a for a in accounts if a.created_at >= since]
        dead = sum(1 for a in recent if a.status == AccountStatus.DEAD)
        active = sum(1 for a in accounts if a.status == AccountStatus.ACTIVE)
        return {
            "total": len(accounts),
            "active": active,
            "dead_recent": dead,
            "mortality_pct": round(dead / max(len(recent), 1) * 100, 1),
            "mortality_target_pct": 10,
        }

    async def daily_metrics(self, session: AsyncSession, days: int = 14) -> list[dict]:
        rows = []
        for i in range(days):
            day = datetime.now(timezone.utc).replace(tzinfo=None).date() - timedelta(days=days - 1 - i)
            start = datetime.combine(day, datetime.min.time())
            end = start + timedelta(days=1)
            msgs = await session.execute(
                select(OutreachMessage).where(
                    OutreachMessage.created_at >= start,
                    OutreachMessage.created_at < end,
                )
            )
            messages = msgs.scalars().all()
            apps = await session.execute(
                select(func.count(Lead.id)).where(
                    Lead.application_at >= start,
                    Lead.application_at < end,
                )
            )
            rows.append({
                "date": day.isoformat(),
                "messages_sent": len(messages),
                "delivered": sum(1 for m in messages if m.delivery_status == DeliveryStatus.DELIVERED),
                "applications": apps.scalar() or 0,
            })
        return rows
