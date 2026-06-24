import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.models.entities import Lead, SalesHandoff

logger = logging.getLogger(__name__)


class NotificationService:
    """Instant sales notifications on new applications (pain #8)."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def notify_new_lead(
        self, session: AsyncSession, lead: Lead, handoff: SalesHandoff
    ) -> bool:
        token = self.settings.sales_telegram_bot_token
        chat_id = self.settings.sales_telegram_chat_id
        if not token or not chat_id:
            logger.warning("Sales notification not configured (bot token / chat id)")
            return False

        name = lead.first_name or lead.username or str(lead.tg_user_id)
        text = (
            f"🔥 НОВАЯ ЗАЯВКА\n\n"
            f"Лид: {name}\n"
            f"Username: @{lead.username or '—'}\n"
            f"ID: {lead.tg_user_id}\n"
            f"Источник: {lead.source_type} / {lead.source_ref}\n"
            f"SLA: связаться до {handoff.sla_deadline_at.strftime('%d.%m %H:%M') if handoff.sla_deadline_at else '—'}\n\n"
            f"⚡ Свяжитесь СЕЙЧАС, не откладывайте на завтра!"
        )

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url,
                    json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                )
                resp.raise_for_status()
            handoff.notified_at = datetime.now(timezone.utc).replace(tzinfo=None)
            return True
        except Exception as exc:
            logger.error("Failed to notify sales: %s", exc)
            return False

    async def check_sla_breaches(self, session: AsyncSession) -> int:
        from sqlalchemy import select

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await session.execute(
            select(SalesHandoff).where(
                SalesHandoff.first_contact_at.is_(None),
                SalesHandoff.sla_breached.is_(False),
                SalesHandoff.sla_deadline_at < now,
            )
        )
        breaches = result.scalars().all()
        for handoff in breaches:
            handoff.sla_breached = True
            token = self.settings.sales_telegram_bot_token
            chat_id = self.settings.sales_telegram_chat_id
            if token and chat_id:
                text = f"⚠️ SLA НАРУШЕН: лид #{handoff.lead_id} — нет контакта 24ч!"
                try:
                    async with httpx.AsyncClient(timeout=15) as client:
                        await client.post(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            json={"chat_id": chat_id, "text": text},
                        )
                except Exception:
                    pass
        return len(breaches)
