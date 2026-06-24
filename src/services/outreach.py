import logging
import random
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import (
    FloodWaitError,
    PeerFloodError,
    UserBannedInChannelError,
    UserPrivacyRestrictedError,
)

from src.config import get_settings
from src.models.entities import (
    ABVariant,
    Account,
    AccountStatus,
    DeliveryStatus,
    Lead,
    LeadStatus,
    OutreachConfig,
    OutreachMessage,
)
from src.services.account_manager import AccountManager
from src.services.telegram_client import TelegramClientFactory, send_with_typing
from src.utils.analytics import track_event
from src.utils.text import expand_spintax, random_delay

logger = logging.getLogger(__name__)


class SpamDetector:
    """Detect spam-blocked accounts and mark for quarantine/pause."""

    SPAM_ERRORS = (PeerFloodError, UserBannedInChannelError)

    @staticmethod
    def is_spam_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return isinstance(exc, SpamDetector.SPAM_ERRORS) or any(
            k in msg for k in ("spam", "flood", "too many", "banned")
        )

    @staticmethod
    async def handle_account_spam(
        session: AsyncSession, account: Account, reason: str
    ) -> None:
        manager = AccountManager()
        account.status = AccountStatus.SPAM_PAUSED
        account.notes = reason
        await track_event(
            session,
            "account_spam_paused",
            account_id=account.id,
            payload={"reason": reason},
        )
        logger.warning("Account %s spam-paused: %s", account.phone, reason)


class OutreachEngine:
    """Mass outreach with spintax, typing simulation, rotation, and auto-retry."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.factory = TelegramClientFactory()
        self.spam_detector = SpamDetector()
        self.account_manager = AccountManager()

    async def _pick_ab_variant(self, session: AsyncSession) -> ABVariant | None:
        result = await session.execute(
            select(ABVariant).where(ABVariant.is_active.is_(True))
        )
        variants = list(result.scalars().all())
        if not variants:
            return None
        weights = [v.weight for v in variants]
        return random.choices(variants, weights=weights, k=1)[0]

    async def _get_active_config(self, session: AsyncSession) -> OutreachConfig | None:
        result = await session.execute(
            select(OutreachConfig).where(OutreachConfig.is_active.is_(True)).limit(1)
        )
        return result.scalar_one_or_none()

    async def _next_account(self, session: AsyncSession) -> Account | None:
        today = datetime.now(timezone.utc).replace(tzinfo=None).date()
        result = await session.execute(
            select(Account).where(Account.status == AccountStatus.ACTIVE)
        )
        accounts = list(result.scalars().all())
        random.shuffle(accounts)
        for account in accounts:
            if account.daily_reset_at is None or account.daily_reset_at.date() < today:
                account.messages_sent_today = 0
                account.daily_reset_at = datetime.now(timezone.utc).replace(tzinfo=None)
            if account.messages_sent_today < self.settings.outreach_daily_limit_per_account:
                return account
        return None

    async def _leads_to_contact(self, session: AsyncSession, limit: int = 10) -> list[Lead]:
        retry_result = await session.execute(
            select(OutreachMessage.lead_id)
            .where(OutreachMessage.delivery_status == DeliveryStatus.RETRY)
            .distinct()
            .limit(limit)
        )
        retry_lead_ids = [row[0] for row in retry_result.all()]

        leads: list[Lead] = []
        if retry_lead_ids:
            retry_leads = await session.execute(
                select(Lead).where(Lead.id.in_(retry_lead_ids))
            )
            leads = list(retry_leads.scalars().all())

        remaining = limit - len(leads)
        if remaining > 0:
            result = await session.execute(
                select(Lead).where(Lead.status == LeadStatus.NEW).limit(remaining)
            )
            leads.extend(result.scalars().all())
        return leads

    def _render_message(self, template: str, lead: Lead, variant: ABVariant | None) -> str:
        text = variant.outreach_template if variant else template
        text = text.replace("{name}", lead.first_name or "друг")
        text = text.replace("{username}", lead.username or "")
        if "{" in text and "|" in text:
            text = expand_spintax(text)
        return text

    async def send_batch(self, session: AsyncSession, batch_size: int = 10) -> dict:
        config = await self._get_active_config(session)
        template = (
            config.message_template
            if config
            else "{Привет|Здравствуйте}, {name}! {Интересное предложение|Есть идея} — напиши, расскажу подробнее."
        )
        use_spintax = config.spintax_enabled if config else True
        use_typing = config.typing_simulation if config else True

        leads = await self._leads_to_contact(session, batch_size)
        stats = {"sent": 0, "delivered": 0, "failed": 0, "spam": 0, "retries": 0}

        for lead in leads:
            account = await self._next_account(session)
            if not account:
                logger.info("No available accounts for outreach")
                break

            variant = lead.ab_variant or await self._pick_ab_variant(session)
            if variant and not lead.ab_variant_id:
                lead.ab_variant_id = variant.id

            text = self._render_message(template, lead, variant)
            if use_spintax:
                text = expand_spintax(text)

            msg = OutreachMessage(
                lead_id=lead.id,
                account_id=account.id,
                text=text,
                delivery_status=DeliveryStatus.PENDING,
            )
            session.add(msg)
            await session.flush()

            delay = random_delay(
                self.settings.outreach_min_delay_sec,
                self.settings.outreach_max_delay_sec,
            )
            import asyncio

            await asyncio.sleep(delay)

            try:
                client = await self.factory.connect(account, account.proxy)
                entity = await client.get_entity(lead.tg_user_id)
                if use_typing:
                    await send_with_typing(client, entity, text)
                else:
                    await client.send_message(entity, text)
                await client.disconnect()

                msg.delivery_status = DeliveryStatus.DELIVERED
                msg.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
                lead.status = LeadStatus.WRITTEN
                lead.assigned_account_id = account.id
                account.messages_sent_today += 1
                stats["sent"] += 1
                stats["delivered"] += 1

                await track_event(
                    session,
                    "message_delivered",
                    lead_id=lead.id,
                    account_id=account.id,
                    cost_rub=account.cost_rub / max(self.settings.outreach_daily_limit_per_account * 30, 1),
                )
            except UserPrivacyRestrictedError:
                msg.delivery_status = DeliveryStatus.FAILED
                msg.error = "privacy_restricted"
                lead.status = LeadStatus.LOST
                stats["failed"] += 1
            except FloodWaitError as exc:
                msg.delivery_status = DeliveryStatus.RETRY
                msg.error = f"flood_wait_{exc.seconds}"
                lead.retry_count += 1
                stats["retries"] += 1
            except Exception as exc:
                if self.spam_detector.is_spam_error(exc):
                    msg.delivery_status = DeliveryStatus.SPAM
                    msg.error = str(exc)
                    await self.spam_detector.handle_account_spam(session, account, str(exc))
                    lead.retry_count += 1
                    stats["spam"] += 1
                    if lead.retry_count < 3:
                        msg.delivery_status = DeliveryStatus.RETRY
                        stats["retries"] += 1
                else:
                    msg.delivery_status = DeliveryStatus.FAILED
                    msg.error = str(exc)
                    stats["failed"] += 1
                    if lead.retry_count < 3:
                        msg.delivery_status = DeliveryStatus.RETRY
                        lead.retry_count += 1
                        stats["retries"] += 1

        return stats

    async def get_delivery_rate(self, session: AsyncSession, days: int = 7) -> dict:
        from datetime import timedelta

        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        result = await session.execute(
            select(OutreachMessage).where(OutreachMessage.created_at >= since)
        )
        messages = result.scalars().all()
        total = len(messages) or 1
        delivered = sum(1 for m in messages if m.delivery_status == DeliveryStatus.DELIVERED)
        spam = sum(1 for m in messages if m.delivery_status == DeliveryStatus.SPAM)
        return {
            "total": len(messages),
            "delivered": delivered,
            "delivery_pct": round(delivered / total * 100, 1),
            "spam": spam,
            "target_pct": self.settings.delivery_target_pct,
            "on_target": delivered / total * 100 >= self.settings.delivery_target_pct,
        }
