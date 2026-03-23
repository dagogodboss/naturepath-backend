"""
Celery Configuration - Background Task Queue
"""
from celery import Celery
from core.config import settings

# Create Celery app
celery_app = Celery(
    "natural_path_spa",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "workers.notification_worker",
        "workers.booking_worker",
        "workers.slot_worker"
    ]
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes
    task_soft_time_limit=240,  # 4 minutes
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # Retry settings
    task_default_retry_delay=60,  # 1 minute
    task_max_retries=3,
    
    # Beat schedule for periodic tasks
    beat_schedule={
        "release-expired-slot-locks": {
            "task": "workers.slot_worker.release_expired_locks",
            "schedule": 60.0,  # Every minute
        },
        "send-booking-reminders": {
            "task": "workers.notification_worker.send_daily_reminders",
            "schedule": 3600.0,  # Every hour
        },
    }
)
