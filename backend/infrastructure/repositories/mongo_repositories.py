"""
MongoDB Repository Implementations - Infrastructure Layer
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorDatabase
from domain.repositories import (
    IUserRepository,
    IPractitionerRepository,
    IServiceRepository,
    IBookingRepository,
    IAvailabilitySlotRepository,
    IPaymentRepository,
    INotificationRepository
)


class MongoUserRepository(IUserRepository):
    """MongoDB implementation of User repository"""
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.users
    
    async def create(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        await self.collection.insert_one(entity)
        return await self.get_by_id(entity["user_id"])
    
    async def get_by_id(self, entity_id: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"user_id": entity_id}, {"_id": 0})
    
    async def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"email": email}, {"_id": 0})
    
    async def get_by_role(self, role: str) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"role": role}, {"_id": 0})
        return await cursor.to_list(length=None)
    
    async def update(self, entity_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.collection.update_one({"user_id": entity_id}, {"$set": data})
        return await self.get_by_id(entity_id)
    
    async def delete(self, entity_id: str) -> bool:
        result = await self.collection.delete_one({"user_id": entity_id})
        return result.deleted_count > 0
    
    async def list_all(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        cursor = self.collection.find({}, {"_id": 0}).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)


class MongoPractitionerRepository(IPractitionerRepository):
    """MongoDB implementation of Practitioner repository"""
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.practitioners
    
    async def create(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        await self.collection.insert_one(entity)
        return await self.get_by_id(entity["practitioner_id"])
    
    async def get_by_id(self, entity_id: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"practitioner_id": entity_id}, {"_id": 0})
    
    async def get_by_user_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"user_id": user_id}, {"_id": 0})
    
    async def get_featured(self) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"is_featured": True}, {"_id": 0})
        return await cursor.to_list(length=None)
    
    async def get_by_service(self, service_id: str) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"services": service_id}, {"_id": 0})
        return await cursor.to_list(length=None)
    
    async def update(self, entity_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.collection.update_one({"practitioner_id": entity_id}, {"$set": data})
        return await self.get_by_id(entity_id)
    
    async def delete(self, entity_id: str) -> bool:
        result = await self.collection.delete_one({"practitioner_id": entity_id})
        return result.deleted_count > 0
    
    async def list_all(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        cursor = self.collection.find({}, {"_id": 0}).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)


class MongoServiceRepository(IServiceRepository):
    """MongoDB implementation of Service repository"""
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.services
    
    async def create(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        await self.collection.insert_one(entity)
        return await self.get_by_id(entity["service_id"])
    
    async def get_by_id(self, entity_id: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"service_id": entity_id}, {"_id": 0})
    
    async def get_by_category(self, category: str) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"category": category, "is_active": True}, {"_id": 0})
        return await cursor.to_list(length=None)
    
    async def get_featured(self) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"is_featured": True, "is_active": True}, {"_id": 0})
        return await cursor.to_list(length=None)
    
    async def get_active(self) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"is_active": True}, {"_id": 0})
        return await cursor.to_list(length=None)
    
    async def update(self, entity_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.collection.update_one({"service_id": entity_id}, {"$set": data})
        return await self.get_by_id(entity_id)
    
    async def delete(self, entity_id: str) -> bool:
        result = await self.collection.delete_one({"service_id": entity_id})
        return result.deleted_count > 0
    
    async def list_all(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        cursor = self.collection.find({}, {"_id": 0}).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)


class MongoBookingRepository(IBookingRepository):
    """MongoDB implementation of Booking repository"""
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.bookings
    
    async def create(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        await self.collection.insert_one(entity)
        return await self.get_by_id(entity["booking_id"])
    
    async def get_by_id(self, entity_id: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"booking_id": entity_id}, {"_id": 0})
    
    async def get_by_customer(self, customer_id: str) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"customer_id": customer_id}, {"_id": 0}).sort("created_at", -1)
        return await cursor.to_list(length=None)
    
    async def get_by_practitioner(self, practitioner_id: str) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"practitioner_id": practitioner_id}, {"_id": 0}).sort("slot.date", 1)
        return await cursor.to_list(length=None)
    
    async def get_by_date_range(
        self, 
        start_date: str, 
        end_date: str, 
        practitioner_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = {"slot.date": {"$gte": start_date, "$lte": end_date}}
        if practitioner_id:
            query["practitioner_id"] = practitioner_id
        cursor = self.collection.find(query, {"_id": 0}).sort("slot.date", 1)
        return await cursor.to_list(length=None)
    
    async def get_by_status(self, status: str) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"status": status}, {"_id": 0})
        return await cursor.to_list(length=None)
    
    async def update(self, entity_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.collection.update_one({"booking_id": entity_id}, {"$set": data})
        return await self.get_by_id(entity_id)
    
    async def delete(self, entity_id: str) -> bool:
        result = await self.collection.delete_one({"booking_id": entity_id})
        return result.deleted_count > 0
    
    async def list_all(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        cursor = self.collection.find({}, {"_id": 0}).skip(skip).limit(limit).sort("created_at", -1)
        return await cursor.to_list(length=limit)


class MongoAvailabilitySlotRepository(IAvailabilitySlotRepository):
    """MongoDB implementation of Availability Slot repository"""
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.availability_slots
    
    async def create(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        await self.collection.insert_one(entity)
        return await self.get_by_id(entity["slot_id"])
    
    async def get_by_id(self, entity_id: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"slot_id": entity_id}, {"_id": 0})
    
    async def get_available_slots(
        self, 
        practitioner_id: str, 
        date: str
    ) -> List[Dict[str, Any]]:
        # First release any expired locks
        await self.release_expired_locks()
        
        cursor = self.collection.find({
            "practitioner_id": practitioner_id,
            "date": date,
            "status": "available"
        }, {"_id": 0}).sort("start_time", 1)
        return await cursor.to_list(length=None)
    
    async def lock_slot(
        self, 
        slot_id: str, 
        user_id: str, 
        lock_duration_seconds: int = 300
    ) -> bool:
        locked_until = datetime.now(timezone.utc) + timedelta(seconds=lock_duration_seconds)
        result = await self.collection.update_one(
            {"slot_id": slot_id, "status": "available"},
            {"$set": {
                "status": "locked",
                "locked_by": user_id,
                "locked_until": locked_until.isoformat()
            }}
        )
        return result.modified_count > 0
    
    async def release_slot(self, slot_id: str) -> bool:
        result = await self.collection.update_one(
            {"slot_id": slot_id},
            {"$set": {
                "status": "available",
                "locked_by": None,
                "locked_until": None,
                "booking_id": None
            }}
        )
        return result.modified_count > 0
    
    async def release_expired_locks(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        result = await self.collection.update_many(
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
        return result.modified_count
    
    async def update(self, entity_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        await self.collection.update_one({"slot_id": entity_id}, {"$set": data})
        return await self.get_by_id(entity_id)
    
    async def delete(self, entity_id: str) -> bool:
        result = await self.collection.delete_one({"slot_id": entity_id})
        return result.deleted_count > 0
    
    async def list_all(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        cursor = self.collection.find({}, {"_id": 0}).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)
    
    async def create_bulk(self, entities: List[Dict[str, Any]]) -> int:
        """Create multiple slots at once"""
        if not entities:
            return 0
        result = await self.collection.insert_many(entities)
        return len(result.inserted_ids)
    
    async def get_slots_by_practitioner_date_range(
        self,
        practitioner_id: str,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        cursor = self.collection.find({
            "practitioner_id": practitioner_id,
            "date": {"$gte": start_date, "$lte": end_date}
        }, {"_id": 0}).sort([("date", 1), ("start_time", 1)])
        return await cursor.to_list(length=None)


class MongoPaymentRepository(IPaymentRepository):
    """MongoDB implementation of Payment repository"""
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.payments
    
    async def create(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        await self.collection.insert_one(entity)
        return await self.get_by_id(entity["payment_id"])
    
    async def get_by_id(self, entity_id: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"payment_id": entity_id}, {"_id": 0})
    
    async def get_by_booking(self, booking_id: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"booking_id": booking_id}, {"_id": 0})
    
    async def get_by_customer(self, customer_id: str) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"customer_id": customer_id}, {"_id": 0}).sort("created_at", -1)
        return await cursor.to_list(length=None)
    
    async def update(self, entity_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.collection.update_one({"payment_id": entity_id}, {"$set": data})
        return await self.get_by_id(entity_id)
    
    async def delete(self, entity_id: str) -> bool:
        result = await self.collection.delete_one({"payment_id": entity_id})
        return result.deleted_count > 0
    
    async def list_all(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        cursor = self.collection.find({}, {"_id": 0}).skip(skip).limit(limit).sort("created_at", -1)
        return await cursor.to_list(length=limit)


class MongoNotificationRepository(INotificationRepository):
    """MongoDB implementation of Notification repository"""
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.notifications
    
    async def create(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        await self.collection.insert_one(entity)
        return await self.get_by_id(entity["notification_id"])
    
    async def get_by_id(self, entity_id: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"notification_id": entity_id}, {"_id": 0})
    
    async def get_by_user(self, user_id: str, unread_only: bool = False) -> List[Dict[str, Any]]:
        query = {"user_id": user_id}
        if unread_only:
            query["is_read"] = False
        cursor = self.collection.find(query, {"_id": 0}).sort("created_at", -1).limit(50)
        return await cursor.to_list(length=50)
    
    async def mark_as_read(self, notification_id: str) -> bool:
        result = await self.collection.update_one(
            {"notification_id": notification_id},
            {"$set": {"is_read": True}}
        )
        return result.modified_count > 0
    
    async def mark_all_as_read(self, user_id: str) -> int:
        result = await self.collection.update_many(
            {"user_id": user_id, "is_read": False},
            {"$set": {"is_read": True}}
        )
        return result.modified_count
    
    async def update(self, entity_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        await self.collection.update_one({"notification_id": entity_id}, {"$set": data})
        return await self.get_by_id(entity_id)
    
    async def delete(self, entity_id: str) -> bool:
        result = await self.collection.delete_one({"notification_id": entity_id})
        return result.deleted_count > 0
    
    async def list_all(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        cursor = self.collection.find({}, {"_id": 0}).skip(skip).limit(limit).sort("created_at", -1)
        return await cursor.to_list(length=limit)


class MongoEventRepository:
    """MongoDB implementation for Event Sourcing"""
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.events
    
    async def store_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        await self.collection.insert_one(event)
        return await self.collection.find_one({"event_id": event["event_id"]}, {"_id": 0})
    
    async def get_events_by_type(self, event_type: str, limit: int = 100) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"event_type": event_type}, {"_id": 0}).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=limit)
    
    async def get_events_by_aggregate(self, aggregate_id: str, aggregate_field: str) -> List[Dict[str, Any]]:
        cursor = self.collection.find({aggregate_field: aggregate_id}, {"_id": 0}).sort("timestamp", 1)
        return await cursor.to_list(length=None)
