"""
Practitioner Use Cases - Application Layer
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from domain.entities import (
    Practitioner, PractitionerSpecialty, PractitionerAvailability,
    generate_id, utc_now
)
from infrastructure.repositories import (
    MongoPractitionerRepository,
    MongoUserRepository,
    MongoAvailabilitySlotRepository
)
from infrastructure.cache import CacheService

logger = logging.getLogger(__name__)


class PractitionerUseCase:
    """Practitioner management use cases"""
    
    def __init__(
        self,
        practitioner_repo: MongoPractitionerRepository,
        user_repo: MongoUserRepository,
        slot_repo: MongoAvailabilitySlotRepository,
        cache: Optional[CacheService] = None
    ):
        self.practitioner_repo = practitioner_repo
        self.user_repo = user_repo
        self.slot_repo = slot_repo
        self.cache = cache
    
    async def create_practitioner(
        self,
        user_id: str,
        bio: str,
        philosophy: Optional[str] = None,
        specialties: List[Dict] = None,
        certifications: List[str] = None,
        services: List[str] = None,
        availability: List[Dict] = None,
        hourly_rate: float = 0.0,
        is_featured: bool = False
    ) -> Dict[str, Any]:
        """Create a new practitioner profile"""
        # Verify user exists
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise ValueError("User not found")
        
        # Check if practitioner already exists for this user
        existing = await self.practitioner_repo.get_by_user_id(user_id)
        if existing:
            raise ValueError("Practitioner profile already exists for this user")
        
        # Update user role to practitioner
        await self.user_repo.update(user_id, {"role": "practitioner"})
        
        practitioner = Practitioner(
            practitioner_id=generate_id(),
            user_id=user_id,
            bio=bio,
            philosophy=philosophy,
            specialties=[PractitionerSpecialty(**s) for s in (specialties or [])],
            certifications=certifications or [],
            services=services or [],
            availability=[PractitionerAvailability(**a) for a in (availability or [])],
            hourly_rate=hourly_rate,
            is_featured=is_featured
        )
        
        practitioner_dict = practitioner.model_dump()
        practitioner_dict["created_at"] = practitioner_dict["created_at"].isoformat()
        practitioner_dict["updated_at"] = practitioner_dict["updated_at"].isoformat()
        
        await self.practitioner_repo.create(practitioner_dict)
        
        # Invalidate cache
        if self.cache:
            await self.cache.delete(CacheService.practitioners_key())
            await self.cache.delete(CacheService.featured_practitioners_key())
        
        logger.info(f"Practitioner created: {practitioner.practitioner_id}")
        
        # Return with user info
        user.pop("password_hash", None)
        return {**practitioner_dict, "user": user}
    
    async def update_practitioner(
        self,
        practitioner_id: str,
        **updates
    ) -> Dict[str, Any]:
        """Update a practitioner profile"""
        practitioner = await self.practitioner_repo.get_by_id(practitioner_id)
        if not practitioner:
            raise ValueError("Practitioner not found")
        
        # Filter out None values
        updates = {k: v for k, v in updates.items() if v is not None}
        
        # Convert specialty/availability objects if present
        if "specialties" in updates:
            updates["specialties"] = [
                s.model_dump() if hasattr(s, 'model_dump') else s 
                for s in updates["specialties"]
            ]
        if "availability" in updates:
            updates["availability"] = [
                a.model_dump() if hasattr(a, 'model_dump') else a 
                for a in updates["availability"]
            ]
        
        await self.practitioner_repo.update(practitioner_id, updates)
        
        # Invalidate cache
        if self.cache:
            await self.cache.delete(CacheService.practitioners_key())
            await self.cache.delete(CacheService.featured_practitioners_key())
            await self.cache.delete(CacheService.practitioner_key(practitioner_id))
        
        logger.info(f"Practitioner updated: {practitioner_id}")
        return await self.get_practitioner_by_id(practitioner_id)
    
    async def get_practitioner_by_id(self, practitioner_id: str) -> Dict[str, Any]:
        """Get a practitioner by ID with user info"""
        # Check cache first
        if self.cache:
            cached = await self.cache.get(CacheService.practitioner_key(practitioner_id))
            if cached:
                return cached
        
        practitioner = await self.practitioner_repo.get_by_id(practitioner_id)
        if not practitioner:
            raise ValueError("Practitioner not found")
        
        # Get user info
        user = await self.user_repo.get_by_id(practitioner["user_id"])
        if user:
            user.pop("password_hash", None)
        practitioner["user"] = user
        
        # Cache the result
        if self.cache:
            await self.cache.set(CacheService.practitioner_key(practitioner_id), practitioner, ttl=300)
        
        return practitioner
    
    async def get_all_practitioners(self) -> List[Dict[str, Any]]:
        """Get all practitioners with user info"""
        # Check cache first
        if self.cache:
            cached = await self.cache.get(CacheService.practitioners_key())
            if cached:
                return cached
        
        practitioners = await self.practitioner_repo.list_all()
        
        # Add user info
        for practitioner in practitioners:
            user = await self.user_repo.get_by_id(practitioner["user_id"])
            if user:
                user.pop("password_hash", None)
            practitioner["user"] = user
        
        # Cache the result
        if self.cache:
            await self.cache.set(CacheService.practitioners_key(), practitioners, ttl=300)
        
        return practitioners
    
    async def get_featured_practitioners(self) -> List[Dict[str, Any]]:
        """Get featured practitioners"""
        # Check cache first
        if self.cache:
            cached = await self.cache.get(CacheService.featured_practitioners_key())
            if cached:
                return cached
        
        practitioners = await self.practitioner_repo.get_featured()
        
        # Add user info
        for practitioner in practitioners:
            user = await self.user_repo.get_by_id(practitioner["user_id"])
            if user:
                user.pop("password_hash", None)
            practitioner["user"] = user
        
        # Cache the result
        if self.cache:
            await self.cache.set(CacheService.featured_practitioners_key(), practitioners, ttl=300)
        
        return practitioners
    
    async def get_practitioners_by_service(self, service_id: str) -> List[Dict[str, Any]]:
        """Get practitioners that offer a specific service"""
        practitioners = await self.practitioner_repo.get_by_service(service_id)
        
        # Add user info
        for practitioner in practitioners:
            user = await self.user_repo.get_by_id(practitioner["user_id"])
            if user:
                user.pop("password_hash", None)
            practitioner["user"] = user
        
        return practitioners
    
    async def get_availability(
        self,
        practitioner_id: str,
        date: str
    ) -> List[Dict[str, Any]]:
        """Get available time slots for a practitioner on a specific date"""
        # Check cache first
        cache_key = CacheService.availability_key(practitioner_id, date)
        if self.cache:
            cached = await self.cache.get(cache_key)
            if cached:
                return cached
        
        # Get practitioner to check availability rules
        practitioner = await self.practitioner_repo.get_by_id(practitioner_id)
        if not practitioner:
            raise ValueError("Practitioner not found")
        
        # Get existing slots
        slots = await self.slot_repo.get_available_slots(practitioner_id, date)
        
        # If no slots exist, generate them based on practitioner's availability
        if not slots:
            # Parse date to get day of week
            from datetime import datetime as dt
            date_obj = dt.strptime(date, "%Y-%m-%d")
            day_of_week = date_obj.weekday()
            
            # Find availability for this day
            day_availability = None
            for avail in practitioner.get("availability", []):
                if avail.get("day_of_week") == day_of_week and avail.get("is_available", True):
                    day_availability = avail
                    break
            
            if day_availability:
                # Generate slots
                start_hour = int(day_availability["start_time"].split(":")[0])
                end_hour = int(day_availability["end_time"].split(":")[0])
                
                for hour in range(start_hour, end_hour):
                    slot_id = generate_id()
                    slot = {
                        "slot_id": slot_id,
                        "practitioner_id": practitioner_id,
                        "date": date,
                        "start_time": f"{hour:02d}:00",
                        "end_time": f"{hour+1:02d}:00",
                        "status": "available",
                        "booking_id": None,
                        "locked_by": None,
                        "locked_until": None,
                        "created_at": utc_now().isoformat()
                    }
                    await self.slot_repo.create(slot.copy())  # Create copy to avoid _id mutation
                    slots.append(slot)  # Append original without _id
        
        # Cache the result (short TTL for availability)
        if self.cache:
            await self.cache.set(cache_key, slots, ttl=60)
        
        return slots
    
    async def generate_availability_slots(
        self,
        practitioner_id: str,
        start_date: str,
        end_date: str
    ) -> Dict[str, Any]:
        """Generate availability slots for a date range"""
        practitioner = await self.practitioner_repo.get_by_id(practitioner_id)
        if not practitioner:
            raise ValueError("Practitioner not found")
        
        from datetime import datetime as dt
        
        start = dt.strptime(start_date, "%Y-%m-%d")
        end = dt.strptime(end_date, "%Y-%m-%d")
        
        total_slots = 0
        current = start
        
        while current <= end:
            day_of_week = current.weekday()
            date_str = current.strftime("%Y-%m-%d")
            
            # Find availability for this day
            for avail in practitioner.get("availability", []):
                if avail.get("day_of_week") == day_of_week and avail.get("is_available", True):
                    start_hour = int(avail["start_time"].split(":")[0])
                    end_hour = int(avail["end_time"].split(":")[0])
                    
                    for hour in range(start_hour, end_hour):
                        # Check if slot already exists
                        existing = await self.slot_repo.collection.find_one({
                            "practitioner_id": practitioner_id,
                            "date": date_str,
                            "start_time": f"{hour:02d}:00"
                        })
                        
                        if not existing:
                            slot = {
                                "slot_id": generate_id(),
                                "practitioner_id": practitioner_id,
                                "date": date_str,
                                "start_time": f"{hour:02d}:00",
                                "end_time": f"{hour+1:02d}:00",
                                "status": "available",
                                "booking_id": None,
                                "locked_by": None,
                                "locked_until": None,
                                "created_at": utc_now().isoformat()
                            }
                            await self.slot_repo.create(slot)
                            total_slots += 1
                    break
            
            current += timedelta(days=1)
        
        logger.info(f"Generated {total_slots} slots for practitioner {practitioner_id}")
        return {"generated_slots": total_slots, "start_date": start_date, "end_date": end_date}
