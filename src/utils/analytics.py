from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.entities import FunnelEvent


async def track_event(
    session: AsyncSession,
    event_type: str,
    *,
    lead_id: int | None = None,
    account_id: int | None = None,
    cost_rub: float = 0.0,
    payload: dict | None = None,
) -> None:
    session.add(
        FunnelEvent(
            lead_id=lead_id,
            account_id=account_id,
            event_type=event_type,
            cost_rub=cost_rub,
            payload=payload,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )


async def count_events_since(
    session: AsyncSession, event_type: str, since: datetime
) -> int:
    result = await session.execute(
        select(FunnelEvent).where(
            FunnelEvent.event_type == event_type,
            FunnelEvent.created_at >= since,
        )
    )
    return len(result.scalars().all())
