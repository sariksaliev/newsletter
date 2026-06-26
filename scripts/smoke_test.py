"""Smoke test: config, DB, API health, sales notify, dialog bot."""

import asyncio
import sys

import httpx

from src.config import get_settings
from src.db.session import async_session, init_db
from src.models.entities import Lead, LeadStatus
from src.services.dialog_bot import DialogBot
from src.services.notifications import NotificationService
from src.utils.analytics import track_event


async def test_db_and_config() -> dict:
    settings = get_settings()
    await init_db()
    checks = {
        "telegram_api": settings.telegram_api_id not in (0, 12345678)
        and settings.telegram_api_hash not in ("", "your_api_hash"),
        "anthropic_key": bool(settings.anthropic_api_key),
        "sales_bot": bool(settings.sales_telegram_bot_token),
        "sales_chat": bool(settings.sales_telegram_chat_id),
    }
    return checks


async def test_sales_notify() -> dict:
    settings = get_settings()
    if not settings.sales_telegram_bot_token or not settings.sales_telegram_chat_id:
        return {"ok": False, "error": "not configured"}

    url = f"https://api.telegram.org/bot{settings.sales_telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            url,
            json={
                "chat_id": settings.sales_telegram_chat_id,
                "text": "✅ TG Outreach smoke test — уведомления работают",
            },
        )
        body = resp.json()
        return {"ok": resp.status_code == 200 and body.get("ok"), "status": resp.status_code, "error": body.get("description")}


async def test_dialog_flow() -> dict:
    async with async_session() as session:
        lead = Lead(
            tg_user_id=999000001,
            username="smoke_test_user",
            first_name="Test",
            source_type="smoke",
            source_ref="smoke_test",
            status=LeadStatus.WRITTEN,
        )
        session.add(lead)
        await session.flush()
        await track_event(session, "lead_created", lead_id=lead.id)

        bot = DialogBot()
        try:
            reply = await bot.handle_incoming(
                session, lead, "Сколько стоит? Хочу заказать", is_voice=False
            )
        except Exception as exc:
            await session.rollback()
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        await session.commit()

        return {
            "ok": lead.status.value == "application",
            "lead_id": lead.id,
            "lead_status": lead.status.value,
            "reply_preview": reply[:120],
        }


async def test_api_health(base_url: str = "http://127.0.0.1:8000") -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{base_url}/api/health")
            return {"ok": resp.status_code == 200, "body": resp.json()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def main() -> int:
    print("=== TG Outreach Smoke Test ===\n")

    config = await test_db_and_config()
    print("Config:")
    for k, v in config.items():
        print(f"  {'OK' if v else 'FAIL'} {k}")

    print("\nSales notification (Telegram group)...")
    notify = await test_sales_notify()
    print(f"  {'OK' if notify.get('ok') else 'FAIL'}", notify)

    print("\nDialog bot flow (create lead -> hot message -> application)...")
    dialog = await test_dialog_flow()
    print(f"  {'OK' if dialog.get('ok') else 'FAIL'}", dialog)

    print("\nAPI health (server must be running)...")
    health = await test_api_health()
    print(f"  {'OK' if health.get('ok') else 'FAIL'}", health)

    failed = sum(
        1
        for x in [
            notify.get("ok"),
            dialog.get("ok"),
        ]
        if not x
    )
    print(f"\n=== Done: {2 - failed}/2 core tests passed (API separate) ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
