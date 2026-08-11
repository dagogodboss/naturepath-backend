"""
MongoDB Database Connection - Infrastructure Layer
"""
import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Optional
from core.config import settings

logger = logging.getLogger(__name__)


class Database:
    """MongoDB async database connection manager"""
    
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None
    
    @classmethod
    async def connect(cls):
        """Connect to MongoDB"""
        try:
            cls.client = AsyncIOMotorClient(settings.mongo_url)
            cls.db = cls.client[settings.db_name]
            
            # Verify connection
            await cls.client.admin.command('ping')
            logger.info(f"Connected to MongoDB: {settings.db_name}")
            
            # Create indexes
            await cls._create_indexes()
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
    
    @classmethod
    async def disconnect(cls):
        """Disconnect from MongoDB"""
        if cls.client:
            cls.client.close()
            logger.info("Disconnected from MongoDB")
    
    @classmethod
    async def _create_indexes(cls):
        """Create database indexes for optimal performance"""
        if cls.db is None:
            return
        
        # Users collection indexes
        await cls.db.users.create_index("user_id", unique=True)
        await cls.db.users.create_index("email", unique=True)
        await cls.db.users.create_index("role")
        
        # Practitioners collection indexes
        await cls.db.practitioners.create_index("practitioner_id", unique=True)
        await cls.db.practitioners.create_index("user_id", unique=True)
        await cls.db.practitioners.create_index("services")
        await cls.db.practitioners.create_index("is_featured")
        
        # Services collection indexes
        await cls.db.services.create_index("service_id", unique=True)
        await cls.db.services.create_index("category")
        await cls.db.services.create_index("is_featured")
        await cls.db.services.create_index("is_active")
        
        # Bookings collection indexes
        await cls.db.bookings.create_index("booking_id", unique=True)
        await cls.db.bookings.create_index("customer_id")
        await cls.db.bookings.create_index("practitioner_id")
        await cls.db.bookings.create_index("status")
        await cls.db.bookings.create_index([("slot.date", 1), ("slot.start_time", 1)])
        try:
            await cls.db.bookings.create_index(
                "receipt_id",
                unique=True,
                partialFilterExpression={"payment_status": "captured"},
                name="uniq_booking_receipt_when_captured",
            )
        except Exception as exc:
            logger.warning(
                "Could not create partial unique index on bookings.receipt_id: %s", exc
            )


        # Availability slots collection indexes
        await cls.db.availability_slots.create_index("slot_id", unique=True)
        await cls.db.availability_slots.create_index([("practitioner_id", 1), ("date", 1)])
        try:
            await cls.db.availability_slots.create_index(
                [("practitioner_id", 1), ("date", 1), ("start_time", 1)],
                unique=True,
                name="uniq_practitioner_date_start_time",
            )
        except Exception as exc:
            logger.warning(
                "Could not create unique compound index on availability_slots (duplicate legacy rows?): %s",
                exc,
            )
        await cls.db.availability_slots.create_index("status")
        await cls.db.availability_slots.create_index("locked_until")
        
        # Payments collection indexes
        await cls.db.payments.create_index("payment_id", unique=True)
        await cls.db.payments.create_index("booking_id")
        await cls.db.payments.create_index("customer_id")
        
        # Notifications collection indexes
        await cls.db.notifications.create_index("notification_id", unique=True)
        await cls.db.notifications.create_index([("user_id", 1), ("is_read", 1)])
        await cls.db.notifications.create_index("created_at")
        
        # Events collection for event sourcing
        await cls.db.events.create_index("event_id", unique=True)
        await cls.db.events.create_index("event_type")
        await cls.db.events.create_index("timestamp")

        # Authorization audit logs
        await cls.db.authorization_audit.create_index("timestamp")
        await cls.db.authorization_audit.create_index([("user_id", 1), ("timestamp", -1)])

        # Casbin policy overrides (hot-reloaded into enforcer)
        await cls.db.rbac_policy_overrides.create_index([("ptype", 1), ("v0", 1), ("v1", 1)])

        # Booking auto-assignment cursor state (round-robin)
        await cls.db.booking_assignment_state.create_index("state_key", unique=True)

        # Store products / ecommerce orders
        await cls.db.store_products.create_index("product_id", unique=True)
        await cls.db.store_products.create_index("revel_product_id")
        await cls.db.store_products.create_index([("is_active_web", 1), ("category", 1)])
        await cls.db.store_products.create_index([("in_custom_menu", 1), ("is_active_web", 1)])
        await cls.db.store_orders.create_index("order_id", unique=True)
        await cls.db.store_orders.create_index([("customer_id", 1), ("created_at", -1)])
        await cls.db.store_orders.create_index([("fulfillment_status", 1), ("payment_status", 1)])
        await cls.db.payment_links.create_index("link_id", unique=True)
        await cls.db.payment_links.create_index([("ref_type", 1), ("ref_id", 1)])
        await cls.db.payment_links.create_index([("provider", 1), ("status", 1)])
        await cls.db.payment_links.create_index("expires_at")
        # G1: immutable payment events ledger
        await cls.db.payment_events.create_index("event_id", unique=True)
        await cls.db.payment_events.create_index([("ref_type", 1), ("ref_id", 1), ("at", -1)])
        await cls.db.payment_events.create_index("action")
        await cls.db.payment_events.create_index("at")
        # G2: reconciliation reports
        await cls.db.reconciliation_reports.create_index("report_id", unique=True)
        await cls.db.reconciliation_reports.create_index([("date", -1), ("resolved", 1)])
        await cls.db.reconciliation_reports.create_index("ref_id")
        await cls.db.store_admin_audit.create_index([("created_at", -1), ("actor_user_id", 1)])
        await cls.db.webhook_events.create_index([("provider", 1), ("event_id", 1)], unique=True)
        await cls.db.webhook_events.create_index(
            "received_at",
            expireAfterSeconds=settings.revel_webhook_replay_ttl_seconds,
        )
        await cls.db.analytics_events.create_index([("event_name", 1), ("created_at", -1)])
        await cls.db.analytics_events.create_index("created_at")

        # Blog / vlog content
        await cls.db.content_posts.create_index("post_id", unique=True)
        await cls.db.content_posts.create_index("slug", unique=True)
        await cls.db.content_posts.create_index([("status", 1), ("type", 1), ("published_at", -1)])
        await cls.db.content_posts.create_index([("updated_at", -1)])
        
        logger.info("Database indexes created")
    
    @classmethod
    def get_db(cls) -> AsyncIOMotorDatabase:
        """Get database instance"""
        if cls.db is None:
            raise RuntimeError("Database not connected")
        return cls.db


def get_database() -> AsyncIOMotorDatabase:
    """Dependency injection for database"""
    return Database.get_db()
