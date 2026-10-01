"""Persist engine and gallery-dl options for presets and scheduled tasks."""

from sqlalchemy import text


async def upgrade(c):
    for table in ("presets", "tasks"):
        await c.execute(text(f"ALTER TABLE {table} ADD COLUMN engine TEXT NOT NULL DEFAULT 'auto'"))
        await c.execute(text(f"ALTER TABLE {table} ADD COLUMN gallerydl TEXT NOT NULL DEFAULT ''"))


async def downgrade(c):
    for table in ("presets", "tasks"):
        await c.execute(text(f"ALTER TABLE {table} DROP COLUMN gallerydl"))
        await c.execute(text(f"ALTER TABLE {table} DROP COLUMN engine"))
