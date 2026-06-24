import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.tl.types import Channel, User

from src.models.entities import Account, AccountStatus, Lead, LeadStatus, ParseJob
from src.services.telegram_client import TelegramClientFactory
from src.utils.analytics import track_event

logger = logging.getLogger(__name__)


class LeadParser:
    """Parse target audience from channels and keyword searches into unified lead DB."""

    def __init__(self) -> None:
        self.factory = TelegramClientFactory()

    async def _get_parser_account(self, session: AsyncSession) -> Account | None:
        result = await session.execute(
            select(Account).where(
                Account.status.in_([AccountStatus.ACTIVE, AccountStatus.READY])
            ).limit(1)
        )
        return result.scalar_one_or_none()

    async def parse_channel(
        self, session: AsyncSession, channel: str, limit: int = 500
    ) -> ParseJob:
        account = await self._get_parser_account(session)
        if not account:
            raise RuntimeError("No active account available for parsing")

        job = ParseJob(
            job_type="channel",
            target=channel,
            account_id=account.id,
            status="running",
        )
        session.add(job)
        await session.flush()

        found = 0
        client = await self.factory.connect(account, account.proxy)
        try:
            entity = await client.get_entity(channel)
            if not isinstance(entity, Channel):
                job.status = "failed"
                return job

            async for user in client.iter_participants(entity, limit=limit):
                if not isinstance(user, User) or user.bot or user.deleted:
                    continue
                lead = await self._upsert_lead(
                    session,
                    tg_user_id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    source_type="channel",
                    source_ref=channel,
                )
                if lead:
                    found += 1
        except Exception as exc:
            logger.error("Parse channel %s failed: %s", channel, exc)
            job.status = "failed"
        finally:
            await client.disconnect()

        job.leads_found = found
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await track_event(
            session,
            "parse_completed",
            account_id=account.id,
            payload={"channel": channel, "found": found},
        )
        return job

    async def parse_keyword_search(
        self, session: AsyncSession, keyword: str, limit: int = 200
    ) -> ParseJob:
        account = await self._get_parser_account(session)
        if not account:
            raise RuntimeError("No active account available for parsing")

        job = ParseJob(
            job_type="keyword",
            target=keyword,
            account_id=account.id,
            status="running",
        )
        session.add(job)
        await session.flush()

        found = 0
        client = await self.factory.connect(account, account.proxy)
        try:
            from telethon.tl.functions.contacts import SearchRequest

            result = await client(SearchRequest(q=keyword, limit=limit))
            for chat in result.chats:
                if isinstance(chat, Channel):
                    sub_found = await self._parse_channel_participants(
                        session, client, chat.username or str(chat.id), 100, keyword
                    )
                    found += sub_found
        except Exception as exc:
            logger.error("Keyword parse %s failed: %s", keyword, exc)
            job.status = "failed"
        finally:
            await client.disconnect()

        job.leads_found = found
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        return job

    async def _parse_channel_participants(
        self,
        session: AsyncSession,
        client,
        channel: str,
        limit: int,
        keyword: str,
    ) -> int:
        found = 0
        try:
            entity = await client.get_entity(channel)
            async for user in client.iter_participants(entity, limit=limit):
                if not isinstance(user, User) or user.bot:
                    continue
                lead = await self._upsert_lead(
                    session,
                    tg_user_id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    source_type="keyword",
                    source_ref=keyword,
                )
                if lead:
                    found += 1
        except Exception as exc:
            logger.debug("Sub-parse failed: %s", exc)
        return found

    async def _upsert_lead(
        self,
        session: AsyncSession,
        tg_user_id: int,
        username: str | None,
        first_name: str | None,
        source_type: str,
        source_ref: str,
    ) -> Lead | None:
        result = await session.execute(
            select(Lead).where(Lead.tg_user_id == tg_user_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return None

        lead = Lead(
            tg_user_id=tg_user_id,
            username=username,
            first_name=first_name,
            source_type=source_type,
            source_ref=source_ref,
            status=LeadStatus.NEW,
        )
        session.add(lead)
        await session.flush()
        await track_event(session, "lead_created", lead_id=lead.id)
        return lead
