"""Seed default A/B variant and outreach config for first run."""

import asyncio

from src.db.session import async_session, init_db
from src.models.entities import ABVariant, OutreachConfig
from src.services.dialog_bot import DEFAULT_SYSTEM_PROMPT


async def seed():
    await init_db()
    async with async_session() as session:
        from sqlalchemy import select

        existing = await session.execute(select(ABVariant).limit(1))
        if not existing.scalar_one_or_none():
            session.add(
                ABVariant(
                    name="default",
                    outreach_template=(
                        "{Привет|Здравствуйте}, {name}! "
                        "{Увидел ваш профиль|Наткнулся на вас} — "
                        "{есть интересное предложение|хочу предложить кое-что полезное}. "
                        "{Напишите|Ответьте}, расскажу подробнее?"
                    ),
                    system_prompt=DEFAULT_SYSTEM_PROMPT,
                    bot_link="https://t.me/your_main_bot",
                    weight=100,
                )
            )

        existing_cfg = await session.execute(select(OutreachConfig).limit(1))
        if not existing_cfg.scalar_one_or_none():
            session.add(
                OutreachConfig(
                    name="default",
                    message_template=(
                        "{Привет|Здравствуйте}, {name}! "
                        "{Есть идея|Хочу предложить} — напишите, расскажу."
                    ),
                    spintax_enabled=True,
                    typing_simulation=True,
                    is_active=True,
                )
            )

        await session.commit()
    print("Seed completed.")


if __name__ == "__main__":
    asyncio.run(seed())
