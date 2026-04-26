"""
Store worker tasks (hold expiry).
"""
import asyncio
import logging
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

from core.config import settings
from infrastructure.external import RevelService
from infrastructure.external.revel_live_client import RevelLiveError
from infrastructure.queue.celery_config import celery_app

logger = logging.getLogger(__name__)


def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _expire_walk_in_holds() -> int:
    client = AsyncIOMotorClient(settings.mongo_url)
    try:
        db = client[settings.db_name]
        now = datetime.now(timezone.utc).isoformat()

        rows = await db.store_orders.find(
            {
                "payment_status": "awaiting_counter",
                "hold_expires_at": {"$lt": now},
            },
            {"_id": 0, "order_id": 1, "revel_order_id": 1},
        ).to_list(length=500)

        revel = RevelService()
        changed = 0
        for row in rows:
            order_id = row.get("order_id")
            revel_order_id = row.get("revel_order_id")
            cancelled_remote = True
            if revel_order_id:
                try:
                    await revel.update_order_status(str(revel_order_id), "cancelled")
                except RevelLiveError:
                    cancelled_remote = False
                    logger.warning(
                        "Failed to cancel Revel hold order_id=%s revel_order_id=%s",
                        order_id,
                        revel_order_id,
                    )
            if not cancelled_remote:
                await db.store_orders.update_one(
                    {"order_id": order_id, "payment_status": "awaiting_counter"},
                    {
                        "$set": {
                            "payment_status": "expiry_pending_remote_cancel",
                            "updated_at": now,
                        },
                        "$push": {"timeline": {"status": "hold_expiry_remote_cancel_failed", "at": now}},
                    },
                )
                continue
            res = await db.store_orders.update_one(
                {"order_id": order_id, "payment_status": "awaiting_counter"},
                {
                    "$set": {
                        "payment_status": "expired",
                        "updated_at": now,
                    },
                    "$push": {
                        "timeline": {"status": "hold_expired", "at": now}
                    },
                },
            )
            changed += int(res.modified_count or 0)

        return changed
    finally:
        client.close()


@celery_app.task
def expire_walk_in_holds():
    try:
        count = run_async(_expire_walk_in_holds())
        logger.info("Expired %s walk-in holds", count)
        return {"expired_count": count}
    except Exception as exc:
        logger.error("Failed to expire walk-in holds: %s", exc)
        raise
