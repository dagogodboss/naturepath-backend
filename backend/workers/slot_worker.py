"""
Slot Worker - Celery Background Tasks
"""
import asyncio
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone
from infrastructure.queue.celery_config import celery_app
from core.config import settings

logger = logging.getLogger(__name__)


def run_async(coro):
    """Helper to run async functions in Celery"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _release_expired_locks():
    """Release all expired slot locks"""
    client = AsyncIOMotorClient(settings.mongo_url)
    db = client[settings.db_name]
    
    now = datetime.now(timezone.utc).isoformat()
    result = await db.availability_slots.update_many(
        {
            "status": "locked",
            "locked_until": {"$lt": now}
        },
        {"$set": {
            "status": "available",
            "locked_by": None,
            "locked_until": None
        }}
    )
    
    client.close()
    return result.modified_count


@celery_app.task
def release_expired_locks():
    """
    Periodic task to release expired slot locks
    Prevents race conditions and slot hoarding
    """
    try:
        count = run_async(_release_expired_locks())
        logger.info(f"Released {count} expired slot locks")
        return {"released_count": count}
    except Exception as e:
        logger.error(f"Failed to release expired locks: {e}")
        return {"error": str(e)}


async def _generate_practitioner_slots(
    practitioner_id: str,
    date: str,
    start_hour: int = 9,
    end_hour: int = 18,
    slot_duration_minutes: int = 60
):
    """Generate availability slots for a practitioner"""
    import uuid
    
    client = AsyncIOMotorClient(settings.mongo_url)
    db = client[settings.db_name]
    
    slots = []
    current_hour = start_hour
    
    while current_hour < end_hour:
        slot_id = str(uuid.uuid4())
        start_time = f"{current_hour:02d}:00"
        end_minutes = current_hour * 60 + slot_duration_minutes
        end_time = f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
        
        slots.append({
            "slot_id": slot_id,
            "practitioner_id": practitioner_id,
            "date": date,
            "start_time": start_time,
            "end_time": end_time,
            "status": "available",
            "booking_id": None,
            "locked_by": None,
            "locked_until": None,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        
        current_hour += 1
    
    if slots:
        await db.availability_slots.insert_many(slots)
    
    client.close()
    return len(slots)


@celery_app.task
def generate_practitioner_slots(
    practitioner_id: str,
    date: str,
    start_hour: int = 9,
    end_hour: int = 18
):
    """Generate availability slots for a practitioner on a given date"""
    try:
        count = run_async(
            _generate_practitioner_slots(
                practitioner_id=practitioner_id,
                date=date,
                start_hour=start_hour,
                end_hour=end_hour
            )
        )
        logger.info(f"Generated {count} slots for practitioner {practitioner_id} on {date}")
        return {"generated_count": count}
    except Exception as e:
        logger.error(f"Failed to generate slots: {e}")
        return {"error": str(e)}
