import logging
from pathlib import Path
from typing import Any

from python_socks import ProxyType
from telethon import TelegramClient

from src.config import Settings, get_settings
from src.models.entities import Account, Proxy

logger = logging.getLogger(__name__)

PROXY_TYPE_MAP = {
    "socks5": ProxyType.SOCKS5,
    "socks4": ProxyType.SOCKS4,
    "http": ProxyType.HTTP,
}


def _proxy_tuple(proxy: Proxy | None) -> tuple | None:
    if not proxy:
        return None
    ptype = PROXY_TYPE_MAP.get(proxy.proxy_type, ProxyType.SOCKS5)
    if proxy.username and proxy.password:
        return (ptype, proxy.host, proxy.port, True, proxy.username, proxy.password)
    return (ptype, proxy.host, proxy.port)


class TelegramClientFactory:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def build(self, account: Account, proxy: Proxy | None = None) -> TelegramClient:
        session = str(Path(account.session_path))
        return TelegramClient(
            session,
            self.settings.telegram_api_id,
            self.settings.telegram_api_hash,
            proxy=_proxy_tuple(proxy),
        )

    async def connect(self, account: Account, proxy: Proxy | None = None) -> TelegramClient:
        client = self.build(account, proxy)
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError(f"Account {account.phone} is not authorized")
        return client


async def send_with_typing(
    client: TelegramClient, entity: Any, text: str, typing_sec: float = 3.0
) -> Any:
    import asyncio

    async with client.action(entity, "typing"):
        await asyncio.sleep(min(typing_sec, max(1.0, len(text) * 0.05)))
    return await client.send_message(entity, text)
