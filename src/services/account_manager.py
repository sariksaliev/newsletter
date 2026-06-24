import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.models.entities import Account, AccountStatus
from src.services.profile_generator import ProfileGenerator
from src.services.proxy_manager import ProxyManager
from src.utils.analytics import track_event
from src.utils.text import country_from_phone

logger = logging.getLogger(__name__)


class AccountManager:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.proxy_manager = ProxyManager()
        self.profile_generator = ProfileGenerator()

    async def import_account(
        self,
        session: AsyncSession,
        phone: str,
        session_file_path: str,
        cost_rub: float = 280.0,
    ) -> Account:
        dest = self.settings.sessions_dir / f"{phone.replace('+', '')}.session"
        src = Path(session_file_path)
        if src.exists() and src.resolve() != dest.resolve():
            shutil.copy2(src, dest)

        existing = await session.execute(select(Account).where(Account.phone == phone))
        if existing.scalar_one_or_none():
            raise ValueError(f"Account {phone} already exists")

        account = Account(
            phone=phone,
            session_path=str(dest),
            phone_country=country_from_phone(phone),
            status=AccountStatus.IMPORTED,
            cost_rub=cost_rub,
        )
        session.add(account)
        await session.flush()

        await self.proxy_manager.auto_bind_on_import(session, account)
        account.status = AccountStatus.PROFILE_PENDING
        self.profile_generator.schedule_profile_edit(account)
        await track_event(
            session,
            "account_imported",
            account_id=account.id,
            cost_rub=cost_rub,
            payload={"phone": phone},
        )
        return account

    async def mark_dead(self, session: AsyncSession, account: Account, reason: str) -> None:
        account.status = AccountStatus.DEAD
        account.died_at = datetime.now(timezone.utc).replace(tzinfo=None)
        account.notes = reason
        await track_event(
            session,
            "account_died",
            account_id=account.id,
            payload={"reason": reason},
        )

    async def quarantine(self, session: AsyncSession, account: Account, reason: str) -> None:
        account.status = AccountStatus.QUARANTINE
        account.notes = reason
        await track_event(
            session,
            "account_quarantine",
            account_id=account.id,
            payload={"reason": reason},
        )

    async def activate_ready(self, session: AsyncSession) -> int:
        result = await session.execute(
            select(Account).where(Account.status == AccountStatus.READY)
        )
        count = 0
        for account in result.scalars().all():
            account.status = AccountStatus.ACTIVE
            count += 1
            await track_event(session, "account_activated", account_id=account.id)
        return count

    async def get_mortality_stats(self, session: AsyncSession, days: int = 30) -> dict:
        from datetime import timedelta

        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        total = await session.execute(
            select(Account).where(Account.created_at >= since)
        )
        all_accounts = total.scalars().all()
        dead = [a for a in all_accounts if a.status == AccountStatus.DEAD]
        total_count = len(all_accounts) or 1
        return {
            "period_days": days,
            "total": len(all_accounts),
            "dead": len(dead),
            "mortality_pct": round(len(dead) / total_count * 100, 1),
            "target_pct": 10,
            "on_target": len(dead) / total_count * 100 < 10,
        }

    async def run_onboarding_pipeline(self, session: AsyncSession) -> dict:
        profiles = await self.profile_generator.process_pending(session)
        activated = await self.activate_ready(session)
        return {"profiles_processed": profiles, "accounts_activated": activated}
