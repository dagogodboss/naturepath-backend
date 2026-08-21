"""Periodic Google Business Profile and Yelp review synchronization."""

from __future__ import annotations

import asyncio
import logging

from motor.motor_asyncio import AsyncIOMotorClient

from application.review_management import import_reviews
from core.config import settings
from infrastructure.external.review_sources import fetch_all_configured_reviews
from infrastructure.queue.celery_config import celery_app


logger = logging.getLogger(__name__)


async def _sync_business_reviews():
    items = await fetch_all_configured_reviews()
    client = AsyncIOMotorClient(settings.mongo_url)
    try:
        result = await import_reviews(client[settings.db_name], items)
    finally:
        client.close()
    return {**result, "fetched": len(items)}


@celery_app.task(bind=True, max_retries=3)
def sync_business_reviews(self):
    try:
        return asyncio.run(_sync_business_reviews())
    except Exception as exc:
        logger.error("Business review sync failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)
