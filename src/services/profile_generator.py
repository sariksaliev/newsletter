import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone

from anthropic import Anthropic
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.tl.functions.account import UpdateBirthdayRequest, UpdateProfileRequest, UpdateUsernameRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
from telethon.tl.functions.stories import SendStoryRequest
from telethon.tl.types import Birthday, InputMediaUploadedPhoto, InputPrivacyValueAllowAll

from src.config import get_settings
from src.models.entities import Account, AccountStatus
from src.services.telegram_client import TelegramClientFactory
from src.utils.analytics import count_events_since, track_event
from src.utils.avatar import generate_avatar, generate_story_image
from src.utils.text import jitter_datetime, random_delay

logger = logging.getLogger(__name__)

PROFILE_PROMPT = """Сгенерируй реалистичный профиль Telegram для обычного пользователя из страны {country}.
Верни ТОЛЬКО JSON без markdown:
{{"first_name": "...", "last_name": "...", "username": "...", "bio": "...", "birth_date": "DD.MM.YYYY", "story_caption": "..."}}
username — латиница, 5-15 символов, уникальный стиль. bio — 1-2 предложения, без рекламы.
story_caption — короткая нейтральная подпись для сторис (до 60 символов)."""


class ProfileGenerator:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Anthropic | None = None

    @property
    def client(self) -> Anthropic:
        if self._client is None:
            self._client = Anthropic(api_key=self.settings.anthropic_api_key)
        return self._client

    def schedule_profile_edit(self, account: Account) -> None:
        """Assign random jitter (15–120 min by default) before profile edit is allowed."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        account.profile_scheduled_at = jitter_datetime(
            now,
            self.settings.profile_edit_jitter_min_sec,
            self.settings.profile_edit_jitter_max_sec,
        )

    async def generate_profile(self, country: str = "RU") -> dict:
        if not self.settings.anthropic_api_key:
            suffix = random.randint(1000, 9999)
            return {
                "first_name": random.choice(["Алексей", "Мария", "Дмитрий", "Анна"]),
                "last_name": random.choice(["Иванов", "Петрова", "Сидоров", "Козлова"]),
                "username": f"user{suffix}",
                "bio": random.choice(
                    ["Люблю путешествия", "Работаю в IT", "Учусь и развиваюсь", "На связи"]
                ),
                "birth_date": f"{random.randint(1,28):02d}.{random.randint(1,12):02d}.{random.randint(1985,2002)}",
                "story_caption": random.choice(["Хорошего дня!", "На связи ✨", "Привет 👋"]),
            }

        response = self.client.messages.create(
            model=self.settings.dialog_model,
            max_tokens=350,
            messages=[
                {"role": "user", "content": PROFILE_PROMPT.format(country=country)}
            ],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(text)

    async def can_edit_now(self, session: AsyncSession) -> bool:
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        count = await count_events_since(session, "profile_edit", since)
        return count < self.settings.max_profile_edits_per_hour

    def _parse_birth_date(self, birth_date: str | None) -> Birthday | None:
        if not birth_date:
            return None
        try:
            parts = birth_date.strip().split(".")
            if len(parts) == 3:
                day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
                return Birthday(day=day, month=month, year=year)
        except (ValueError, IndexError):
            pass
        return None

    async def _upload_avatar(self, client, avatar_path: str) -> None:
        uploaded = await client.upload_file(avatar_path)
        await client(UploadProfilePhotoRequest(file=uploaded))

    async def _set_birthday(self, client, birth_date: str | None) -> None:
        birthday = self._parse_birth_date(birth_date)
        if birthday:
            try:
                await client(UpdateBirthdayRequest(birthday=birthday))
            except Exception as exc:
                logger.warning("Birthday update failed: %s", exc)

    async def _post_story(self, client, account: Account, caption: str | None) -> bool:
        try:
            story_path = generate_story_image(
                caption or "Привет! 👋",
                self.settings.avatars_dir,
                account.phone,
            )
            uploaded = await client.upload_file(str(story_path))
            media = InputMediaUploadedPhoto(file=uploaded)
            me = await client.get_me()
            peer = await client.get_input_entity(me)
            await client(
                SendStoryRequest(
                    peer=peer,
                    media=media,
                    privacy_rules=[InputPrivacyValueAllowAll()],
                    caption=caption,
                    period=86400,
                )
            )
            account.story_posted_at = datetime.now(timezone.utc).replace(tzinfo=None)
            return True
        except Exception as exc:
            logger.warning("Story post failed for %s: %s", account.phone, exc)
            return False

    async def apply_profile(
        self, session: AsyncSession, account: Account, profile: dict
    ) -> None:
        if not await self.can_edit_now(session):
            logger.info("Profile edit rate limit, rescheduling %s", account.phone)
            self.schedule_profile_edit(account)
            return

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if account.profile_scheduled_at and account.profile_scheduled_at > now:
            logger.debug(
                "Profile edit for %s scheduled at %s",
                account.phone,
                account.profile_scheduled_at,
            )
            return

        account.first_name = profile.get("first_name")
        account.last_name = profile.get("last_name")
        account.username = profile.get("username")
        account.bio = profile.get("bio")
        account.birth_date = profile.get("birth_date")

        avatar_path = generate_avatar(
            account.first_name,
            account.last_name,
            self.settings.avatars_dir,
            account.phone,
        )
        account.avatar_path = str(avatar_path)

        factory = TelegramClientFactory()
        proxy = account.proxy
        try:
            client = await factory.connect(account, proxy)

            await client(
                UpdateProfileRequest(
                    first_name=account.first_name or "",
                    last_name=account.last_name or "",
                    about=account.bio or "",
                )
            )

            if account.username:
                try:
                    await client(UpdateUsernameRequest(account.username))
                except Exception as exc:
                    logger.warning("Username update failed for %s: %s", account.phone, exc)

            await self._set_birthday(client, account.birth_date)
            await asyncio.sleep(random_delay(2, 5))
            await self._upload_avatar(client, account.avatar_path)
            await asyncio.sleep(random_delay(3, 8))
            await self._post_story(client, account, profile.get("story_caption"))

            await client.disconnect()
        except Exception as exc:
            logger.error("Failed to apply profile for %s: %s", account.phone, exc)
            account.status = AccountStatus.QUARANTINE
            return

        await track_event(
            session,
            "profile_edit",
            account_id=account.id,
            payload={
                "username": account.username,
                "avatar": True,
                "story": account.story_posted_at is not None,
            },
        )
        account.status = AccountStatus.WARMING
        account.warmup_day = 0
        account.warmup_started_at = datetime.now(timezone.utc).replace(tzinfo=None)
        account.profile_scheduled_at = None

    async def process_pending(self, session: AsyncSession) -> int:
        """Process at most one profile per run — anti-correlation batch + jitter."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = await session.execute(
            select(Account)
            .where(
                Account.status == AccountStatus.PROFILE_PENDING,
                or_(
                    Account.profile_scheduled_at.is_(None),
                    Account.profile_scheduled_at <= now,
                ),
            )
            .order_by(Account.profile_scheduled_at.asc().nullsfirst())
            .limit(1)
        )
        account = result.scalar_one_or_none()
        if not account:
            return 0

        if account.profile_scheduled_at is None:
            self.schedule_profile_edit(account)
            if account.profile_scheduled_at > now:
                return 0

        profile = await self.generate_profile(account.phone_country)
        await self.apply_profile(session, account, profile)
        return 1
