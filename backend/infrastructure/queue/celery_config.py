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
        "workers.slot_worker",
        "workers.store_worker",
        "workers.booking_invoice_worker",
        "workers.reconciliation_worker",
        "workers.refund_reconciliation_worker",
        "workers.media_preview_worker",
        "workers.outlook_calendar_worker",
    ]
)

# Celery configuration
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=settings.celery_task_always_eager,
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
            "schedule": 1800.0,  # Every 30 minutes (d3/d1/d0 windows)
        },
        "expire-walk-in-holds": {
            "task": "workers.store_worker.expire_walk_in_holds",
            "schedule": 900.0,  # Every 15 minutes
        },
        "reconcile-revel-orders": {
            "task": "workers.reconciliation_worker.reconcile_revel_orders",
            "schedule": 86400.0,  # Once a day (02:00 handled by Celery's beat_max_loop_interval)
        },
        "sweep-store-refund-reconciliation": {
            "task": "workers.refund_reconciliation_worker.sweep_store_refund_reconciliation",
            "schedule": 1800.0,  # Every 30 minutes
        },
        "sync-outlook-calendars": {
            "task": "workers.outlook_calendar_worker.sync_all_outlook_calendars",
            "schedule": 300.0,
        },
    }
)
