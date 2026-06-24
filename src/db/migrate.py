"""Lightweight SQLite column migrations for existing databases."""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)

ACCOUNT_COLUMNS = (
    ("profile_scheduled_at", "DATETIME"),
    ("avatar_path", "VARCHAR(512)"),
    ("story_posted_at", "DATETIME"),
)


async def run_migrations(conn: AsyncConnection) -> None:
    if conn.dialect.name != "sqlite":
        return

    for column, col_type in ACCOUNT_COLUMNS:
        await _add_column_if_missing(conn, "accounts", column, col_type)


async def _add_column_if_missing(
    conn: AsyncConnection, table: str, column: str, col_type: str
) -> None:
    result = await conn.execute(text(f"PRAGMA table_info({table})"))
    existing = {row[1] for row in result.fetchall()}
    if column in existing:
        return
    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
    logger.info("Migration: added %s.%s", table, column)
