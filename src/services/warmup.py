import asyncio
import logging
import random
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ReadHistoryRequest, SendReactionRequest
from telethon.tl.types import ReactionEmoji

from src.config import get_settings
from src.models.entities import Account, AccountStatus
from src.services.telegram_client import TelegramClientFactory
from src.utils.analytics import track_event
from src.utils.text import random_delay

logger = logging.getLogger(__name__)

DEFAULT_WARMUP_CHANNELS = [
    "durov",
    "telegram",
    "bbcnews",
    "meduzalive",
    "tassagency",
    "rian_ru",
    "habr_com",
    "vcnews",
]

WARMUP_REACTIONS = ["👍", "❤", "🔥", "👏", "😍", "🎉", "💯"]


class WarmupConveyor:
    """Automated N-day warmup: subscriptions, browsing, reactions, mutual messaging."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.factory = TelegramClientFactory()

    async def _get_warming_accounts(self, session: AsyncSession) -> list[Account]:
        result = await session.execute(
            select(Account).where(Account.status == AccountStatus.WARMING)
        )
        return list(result.scalars().all())

    async def _get_ready_peers(
        self, session: AsyncSession, exclude_id: int
    ) -> list[Account]:
        result = await session.execute(
            select(Account).where(
                Account.status.in_([AccountStatus.WARMING, AccountStatus.READY]),
                Account.id != exclude_id,
            )
        )
        return list(result.scalars().all())

    async def run_daily_cycle(self, session: AsyncSession) -> dict:
        accounts = await self._get_warming_accounts(session)
        stats = {"processed": 0, "completed": 0, "errors": 0, "reactions": 0}

        for account in accounts:
            try:
                completed, reactions = await self._warmup_account(session, account)
                stats["processed"] += 1
                stats["reactions"] += reactions
                if completed:
                    stats["completed"] += 1
            except Exception as exc:
                logger.error("Warmup failed for %s: %s", account.phone, exc)
                stats["errors"] += 1

        return stats

    async def _browse_channel(self, client, entity) -> list:
        """Simulate scrolling/lurking: fetch messages with pauses, mark as read."""
        limit = self.settings.warmup_browse_messages
        messages = await client.get_messages(entity, limit=limit)
        for msg in messages[: min(8, len(messages))]:
            await asyncio.sleep(random_delay(1.5, 4.0))
        if messages:
            try:
                await client(
                    ReadHistoryRequest(
                        peer=entity,
                        max_id=messages[0].id,
                    )
                )
            except Exception as exc:
                logger.debug("ReadHistory failed: %s", exc)
        return messages

    async def _react_to_messages(self, client, entity, messages: list) -> int:
        react_count = 0
        candidates = [m for m in messages if m and m.id and getattr(m, "reactions", None) is not False]
        if not candidates:
            candidates = [m for m in messages if m and m.id]
        if not candidates:
            return 0

        picks = random.sample(
            candidates,
            min(self.settings.warmup_reactions_per_day, len(candidates)),
        )
        for msg in picks:
            try:
                emoji = random.choice(WARMUP_REACTIONS)
                await client(
                    SendReactionRequest(
                        peer=entity,
                        msg_id=msg.id,
                        reaction=[ReactionEmoji(emoticon=emoji)],
                        add_to_recent=True,
                    )
                )
                react_count += 1
                await asyncio.sleep(random_delay(2, 6))
            except FloodWaitError as exc:
                logger.warning("FloodWait on reaction: %ss", exc.seconds)
                break
            except Exception as exc:
                logger.debug("Reaction failed on msg %s: %s", msg.id, exc)
        return react_count

    async def _warmup_account(self, session: AsyncSession, account: Account) -> tuple[bool, int]:
        if account.warmup_started_at is None:
            account.warmup_started_at = datetime.now(timezone.utc).replace(tzinfo=None)

        proxy = account.proxy
        client = await self.factory.connect(account, proxy)
        total_reactions = 0

        try:
            channels = random.sample(
                DEFAULT_WARMUP_CHANNELS,
                min(self.settings.warmup_channels_per_day, len(DEFAULT_WARMUP_CHANNELS)),
            )
            for ch in channels:
                try:
                    entity = await client.get_entity(ch)
                    await client(JoinChannelRequest(entity))
                    await asyncio.sleep(random_delay(3, 8))

                    messages = await self._browse_channel(client, entity)
                    total_reactions += await self._react_to_messages(client, entity, messages)
                except Exception as exc:
                    logger.debug("Channel warmup %s failed: %s", ch, exc)

            peers = await self._get_ready_peers(session, account.id)
            cycles = min(self.settings.warmup_messages_per_day // 2, len(peers), 3)
            for peer_account in random.sample(peers, cycles) if peers else []:
                if not peer_account.username:
                    continue
                try:
                    peer_entity = await client.get_entity(peer_account.username)
                    msgs = [
                        "Привет!",
                        "Как дела?",
                        "Да, нормально",
                        "Ок, на связи",
                    ]
                    for _ in range(2):
                        text = random.choice(msgs)
                        await client.send_message(peer_entity, text)
                        await asyncio.sleep(random_delay(5, 15))
                except FloodWaitError as exc:
                    logger.warning("FloodWait on warmup %s: %ss", account.phone, exc.seconds)
                    break
                except Exception as exc:
                    logger.debug("Mutual msg failed: %s", exc)

            account.warmup_day += 1
            account.last_activity_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await track_event(
                session,
                "warmup_day_completed",
                account_id=account.id,
                payload={"day": account.warmup_day, "reactions": total_reactions},
            )

            if account.warmup_day >= self.settings.warmup_days:
                account.status = AccountStatus.READY
                account.warmup_completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await track_event(session, "warmup_completed", account_id=account.id)
                return True, total_reactions
        finally:
            await client.disconnect()

        return False, total_reactions
