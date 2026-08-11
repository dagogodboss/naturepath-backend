"""Periodic and webhook-triggered Outlook calendar synchronization."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

from application.outlook_sync import sync_outlook_connection
from core.config import settings
from infrastructure.queue.celery_config import celery_app

logger = logging.getLogger(__name__)


async def _sync_one(connection_id: str):
    client = AsyncIOMotorClient(settings.mongo_url)
    try:
        db = client[settings.db_name]
        connection = await db.outlook_calendar_connections.find_one(
            {"connection_id": connection_id, "is_active": True}, {"_id": 0}
        )
        if not connection:
            return {"status": "missing"}
        try:
            return await sync_outlook_connection(db, connection)
        except Exception as exc:
            await db.outlook_calendar_connections.update_one(
                {"connection_id": connection_id},
                {"$set": {
                    "last_sync_status": "error",
                    "last_sync_error": str(exc),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            raise
    finally:
        client.close()


@celery_app.task(bind=True, max_retries=3)
def sync_outlook_connection_task(self, connection_id: str):
    try:
        return asyncio.run(_sync_one(connection_id))
    except Exception as exc:
        logger.error("Outlook sync failed for %s: %s", connection_id, exc)
        self.retry(exc=exc, countdown=60)


async def _sync_all():
    client = AsyncIOMotorClient(settings.mongo_url)
    try:
        rows = await client[settings.db_name].outlook_calendar_connections.find(
            {"is_active": True}, {"_id": 0, "connection_id": 1}
        ).to_list(length=500)
    finally:
        client.close()
    for row in rows:
        sync_outlook_connection_task.delay(row["connection_id"])
    return {"queued": len(rows)}


@celery_app.task
def sync_all_outlook_calendars():
    return asyncio.run(_sync_all())
