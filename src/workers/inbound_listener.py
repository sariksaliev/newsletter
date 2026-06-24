"""Inbound message listener — routes Telegram replies to dialog bot."""

import logging

from sqlalchemy import select
from telethon import events

from src.db.session import async_session
from src.models.entities import Account, AccountStatus, Lead, LeadStatus
from src.services.dialog_bot import DialogBot
from src.services.telegram_client import TelegramClientFactory

logger = logging.getLogger(__name__)


class InboundListener:
    def __init__(self) -> None:
        self.factory = TelegramClientFactory()
        self.bot = DialogBot()
        self._clients = []

    async def start(self) -> None:
        async with async_session() as session:
            result = await session.execute(
                select(Account).where(Account.status == AccountStatus.ACTIVE)
            )
            accounts = result.scalars().all()

        for account in accounts:
            try:
                client = await self.factory.connect(account, account.proxy)
                client.add_event_handler(
                    self._make_handler(account.id),
                    events.NewMessage(incoming=True),
                )
                self._clients.append(client)
                logger.info("Listening on account %s", account.phone)
            except Exception as exc:
                logger.error("Failed to start listener for %s: %s", account.phone, exc)

        if self._clients:
            await self._clients[0].run_until_disconnected()

    def _make_handler(self, account_id: int):
        async def handler(event):
            if not event.is_private:
                return
            sender = await event.get_sender()
            if not sender or getattr(sender, "bot", False):
                return

            async with async_session() as session:
                result = await session.execute(
                    select(Lead).where(Lead.tg_user_id == sender.id)
                )
                lead = result.scalar_one_or_none()
                if not lead:
                    lead = Lead(
                        tg_user_id=sender.id,
                        username=getattr(sender, "username", None),
                        first_name=getattr(sender, "first_name", None),
                        status=LeadStatus.REPLIED,
                        source_type="inbound",
                        assigned_account_id=account_id,
                    )
                    session.add(lead)
                    await session.flush()

                text = event.message.text or ""
                is_voice = bool(event.message.voice)
                if is_voice and event.message.voice:
                    voice = await event.client.download_media(event.message.voice, bytes)
                    text = await self.bot.transcribe_voice(voice)

                if not text:
                    return

                reply = await self.bot.handle_incoming(session, lead, text, is_voice)
                await session.commit()
                await event.respond(reply)

        return handler


async def run_listener():
    listener = InboundListener()
    await listener.start()
