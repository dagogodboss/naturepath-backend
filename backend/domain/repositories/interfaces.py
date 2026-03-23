"""
Repository Interfaces - Domain Layer
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime


class BaseRepository(ABC):
    """Base repository interface"""
    
    @abstractmethod
    async def create(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        pass
    
    @abstractmethod
    async def get_by_id(self, entity_id: str) -> Optional[Dict[str, Any]]:
        pass
    
    @abstractmethod
    async def update(self, entity_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        pass
    
    @abstractmethod
    async def delete(self, entity_id: str) -> bool:
        pass
    
    @abstractmethod
    async def list_all(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        pass


class IUserRepository(BaseRepository):
    """User repository interface"""
    
    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        pass
    
    @abstractmethod
    async def get_by_role(self, role: str) -> List[Dict[str, Any]]:
        pass


class IPractitionerRepository(BaseRepository):
    """Practitioner repository interface"""
    
    @abstractmethod
    async def get_by_user_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        pass
    
    @abstractmethod
    async def get_featured(self) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    async def get_by_service(self, service_id: str) -> List[Dict[str, Any]]:
        pass


class IServiceRepository(BaseRepository):
    """Service repository interface"""
    
    @abstractmethod
    async def get_by_category(self, category: str) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    async def get_featured(self) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    async def get_active(self) -> List[Dict[str, Any]]:
        pass


class IBookingRepository(BaseRepository):
    """Booking repository interface"""
    
    @abstractmethod
    async def get_by_customer(self, customer_id: str) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    async def get_by_practitioner(self, practitioner_id: str) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    async def get_by_date_range(
        self, 
        start_date: str, 
        end_date: str, 
        practitioner_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    async def get_by_status(self, status: str) -> List[Dict[str, Any]]:
        pass


class IAvailabilitySlotRepository(BaseRepository):
    """Availability slot repository interface"""
    
    @abstractmethod
    async def get_available_slots(
        self, 
        practitioner_id: str, 
        date: str
    ) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    async def lock_slot(
        self, 
        slot_id: str, 
        user_id: str, 
        lock_duration_seconds: int
    ) -> bool:
        pass
    
    @abstractmethod
    async def release_slot(self, slot_id: str) -> bool:
        pass
    
    @abstractmethod
    async def release_expired_locks(self) -> int:
        pass


class IPaymentRepository(BaseRepository):
    """Payment repository interface"""
    
    @abstractmethod
    async def get_by_booking(self, booking_id: str) -> Optional[Dict[str, Any]]:
        pass
    
    @abstractmethod
    async def get_by_customer(self, customer_id: str) -> List[Dict[str, Any]]:
        pass


class INotificationRepository(BaseRepository):
    """Notification repository interface"""
    
    @abstractmethod
    async def get_by_user(self, user_id: str, unread_only: bool = False) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    async def mark_as_read(self, notification_id: str) -> bool:
        pass
    
    @abstractmethod
    async def mark_all_as_read(self, user_id: str) -> int:
        pass
