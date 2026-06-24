import logging
from datetime import datetime, timedelta, timezone

import httpx
from anthropic import Anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.models.entities import ABVariant, DialogMessage, Lead, LeadStatus, SalesHandoff
from src.services.notifications import NotificationService
from src.utils.analytics import track_event

logger = logging.getLogger(__name__)

HOT_LEAD_KEYWORDS = [
    "цена", "стоимость", "сколько", "купить", "заказать",
    "интересно", "давайте", "созвон", "звонок", "заявка",
    "хочу", "готов", "подключ", "оформ",
]

DEFAULT_SYSTEM_PROMPT = """Ты — дружелюбный менеджер в Telegram. Веди диалог с потенциальным клиентом.
Цель: квалифицировать интерес и дать ссылку на основного бота: {bot_link}
Правила:
- Короткие сообщения, 1-3 предложения
- Не давить, отвечать на вопросы
- При явном интересе — дай ссылку на бота
- Если клиент готов оформить заявку — подтверди и скажи что менеджер свяжется
"""


class DialogBot:
    """Custom LLM dialog bot with context, voice support, A/B prompts, hot lead handoff."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Anthropic | None = None
        self.notifications = NotificationService()

    @property
    def client(self) -> Anthropic:
        if self._client is None:
            self._client = Anthropic(api_key=self.settings.anthropic_api_key)
        return self._client

    async def _get_variant(self, session: AsyncSession, lead: Lead) -> ABVariant | None:
        if lead.ab_variant_id:
            result = await session.execute(
                select(ABVariant).where(ABVariant.id == lead.ab_variant_id)
            )
            return result.scalar_one_or_none()
        result = await session.execute(
            select(ABVariant).where(ABVariant.is_active.is_(True)).limit(1)
        )
        return result.scalar_one_or_none()

    async def _history(self, session: AsyncSession, lead_id: int) -> list[dict]:
        result = await session.execute(
            select(DialogMessage)
            .where(DialogMessage.lead_id == lead_id)
            .order_by(DialogMessage.created_at)
        )
        return [
            {"role": m.role, "content": m.content}
            for m in result.scalars().all()
        ]

    def _is_hot_lead(self, text: str) -> bool:
        lower = text.lower()
        return any(kw in lower for kw in HOT_LEAD_KEYWORDS)

    async def transcribe_voice(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str:
        if not self.settings.openai_api_key:
            return "[голосовое сообщение — транскрипция недоступна, настройте OPENAI_API_KEY]"

        async with httpx.AsyncClient(timeout=60) as http:
            files = {"file": (filename, audio_bytes, "audio/ogg")}
            data = {"model": "whisper-1", "language": "ru"}
            resp = await http.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                files=files,
                data=data,
            )
            resp.raise_for_status()
            return resp.json()["text"]

    async def handle_incoming(
        self,
        session: AsyncSession,
        lead: Lead,
        user_message: str,
        is_voice: bool = False,
    ) -> str:
        if lead.status == LeadStatus.WRITTEN:
            lead.status = LeadStatus.REPLIED
            await track_event(session, "lead_replied", lead_id=lead.id)

        if lead.status in (LeadStatus.WRITTEN, LeadStatus.REPLIED):
            lead.status = LeadStatus.IN_BOT
            await track_event(session, "lead_in_bot", lead_id=lead.id)

        session.add(
            DialogMessage(
                lead_id=lead.id,
                role="user",
                content=user_message,
                is_voice_transcript=is_voice,
            )
        )

        variant = await self._get_variant(session, lead)
        bot_link = variant.bot_link if variant else "https://t.me/your_main_bot"
        system = (variant.system_prompt if variant else DEFAULT_SYSTEM_PROMPT).format(
            bot_link=bot_link
        )

        history = await self._history(session, lead.id)
        messages = history + [{"role": "user", "content": user_message}]

        if not self.settings.anthropic_api_key:
            reply = (
                f"Спасибо за ответ! Вот ссылка на наш бот: {bot_link}"
                if self._is_hot_lead(user_message)
                else "Расскажите, что вас интересует?"
            )
        else:
            response = self.client.messages.create(
                model=self.settings.dialog_model,
                max_tokens=500,
                system=system,
                messages=messages,
            )
            reply = response.content[0].text

        session.add(DialogMessage(lead_id=lead.id, role="assistant", content=reply))

        if self._is_hot_lead(user_message) or "t.me/" in reply.lower():
            await self._create_application(session, lead)

        return reply

    async def _create_application(self, session: AsyncSession, lead: Lead) -> None:
        if lead.status == LeadStatus.APPLICATION:
            return

        lead.status = LeadStatus.APPLICATION
        lead.application_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await track_event(session, "application_created", lead_id=lead.id)

        sla_deadline = lead.application_at + timedelta(hours=24)
        handoff = SalesHandoff(
            lead_id=lead.id,
            sla_deadline_at=sla_deadline,
        )
        session.add(handoff)
        await session.flush()

        await self.notifications.notify_new_lead(session, lead, handoff)

    async def mark_call(self, session: AsyncSession, lead_id: int) -> Lead | None:
        result = await session.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()
        if not lead:
            return None
        lead.status = LeadStatus.CALL
        lead.call_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await track_event(session, "call_scheduled", lead_id=lead.id)

        handoff_result = await session.execute(
            select(SalesHandoff).where(SalesHandoff.lead_id == lead_id)
        )
        handoff = handoff_result.scalar_one_or_none()
        if handoff and not handoff.first_contact_at:
            handoff.first_contact_at = lead.call_at
        return lead

    async def mark_sale(
        self, session: AsyncSession, lead_id: int, amount_rub: float
    ) -> Lead | None:
        result = await session.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()
        if not lead:
            return None
        lead.status = LeadStatus.SALE
        lead.sale_at = datetime.now(timezone.utc).replace(tzinfo=None)
        lead.sale_amount_rub = amount_rub
        await track_event(
            session, "sale_completed", lead_id=lead.id, cost_rub=0, payload={"amount": amount_rub}
        )
        return lead

    async def get_ab_stats(self, session: AsyncSession) -> list[dict]:
        result = await session.execute(select(ABVariant).where(ABVariant.is_active.is_(True)))
        variants = result.scalars().all()
        stats = []
        for v in variants:
            leads_result = await session.execute(
                select(Lead).where(Lead.ab_variant_id == v.id)
            )
            leads = leads_result.scalars().all()
            replied = sum(1 for l in leads if l.status.value not in ("new", "written"))
            applications = sum(1 for l in leads if l.status.value in ("application", "call", "sale"))
            stats.append({
                "variant_id": v.id,
                "name": v.name,
                "total_leads": len(leads),
                "replied": replied,
                "applications": applications,
                "reply_rate_pct": round(replied / max(len(leads), 1) * 100, 1),
                "application_rate_pct": round(applications / max(replied, 1) * 100, 1),
            })
        return stats
