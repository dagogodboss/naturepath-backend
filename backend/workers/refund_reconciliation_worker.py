"""
Celery entrypoint for refund reconciliation sweeps (G2 follow-up).
"""
from __future__ import annotations

import asyncio
import logging

from motor.motor_asyncio import AsyncIOMotorClient

from core.config import settings
from infrastructure.payment.store_refund_sweep import sweep_store_refund_reconciliation_pending
from infrastructure.queue.celery_config import celery_app

logger = logging.getLogger(__name__)


def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _run_sweep() -> dict:
    client = AsyncIOMotorClient(settings.mongo_url)
    try:
        db = client[settings.db_name]
        return await sweep_store_refund_reconciliation_pending(db)
    finally:
        client.close()


@celery_app.task(bind=True, max_retries=2)
def sweep_store_refund_reconciliation(self):
    try:
        return run_async(_run_sweep())
    except Exception as exc:
        logger.error("sweep_store_refund_reconciliation failed: %s", exc)
        self.retry(exc=exc, countdown=300)
