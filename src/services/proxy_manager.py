import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.models.entities import Account, AccountStatus, Proxy
from src.utils.analytics import track_event
from src.utils.text import country_from_phone

logger = logging.getLogger(__name__)


class ProxyManager:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def add_proxy(
        self,
        session: AsyncSession,
        host: str,
        port: int,
        country: str = "RU",
        username: str | None = None,
        password: str | None = None,
        proxy_type: str = "socks5",
    ) -> Proxy:
        proxy = Proxy(
            host=host,
            port=port,
            country=country.upper(),
            username=username,
            password=password,
            proxy_type=proxy_type,
        )
        session.add(proxy)
        await session.flush()
        return proxy

    async def _count_on_proxy(self, session: AsyncSession, proxy_id: int) -> int:
        result = await session.execute(
            select(func.count(Account.id)).where(
                Account.proxy_id == proxy_id,
                Account.status.notin_([AccountStatus.DEAD]),
            )
        )
        return result.scalar() or 0

    async def assign_proxy(self, session: AsyncSession, account: Account) -> Proxy | None:
        country = account.phone_country or country_from_phone(account.phone)
        result = await session.execute(
            select(Proxy).where(Proxy.is_active.is_(True), Proxy.country == country)
        )
        proxies = result.scalars().all()
        for proxy in proxies:
            count = await self._count_on_proxy(session, proxy.id)
            if count < self.settings.max_accounts_per_proxy:
                account.proxy_id = proxy.id
                account.status = AccountStatus.PROXY_BOUND
                await track_event(
                    session,
                    "proxy_assigned",
                    account_id=account.id,
                    payload={"proxy_id": proxy.id, "country": country},
                )
                return proxy

        result = await session.execute(select(Proxy).where(Proxy.is_active.is_(True)))
        for proxy in result.scalars().all():
            count = await self._count_on_proxy(session, proxy.id)
            if count < self.settings.max_accounts_per_proxy:
                account.proxy_id = proxy.id
                account.status = AccountStatus.PROXY_BOUND
                return proxy
        logger.warning("No available proxy for account %s", account.phone)
        return None

    async def auto_bind_on_import(self, session: AsyncSession, account: Account) -> None:
        account.phone_country = country_from_phone(account.phone)
        await self.assign_proxy(session, account)
