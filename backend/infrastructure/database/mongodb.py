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
        
        # Availability slots collection indexes
        await cls.db.availability_slots.create_index("slot_id", unique=True)
        await cls.db.availability_slots.create_index([("practitioner_id", 1), ("date", 1)])
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
