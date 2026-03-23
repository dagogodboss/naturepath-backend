"""
Service Use Cases - Application Layer
"""
import logging
from typing import Optional, Dict, Any, List
from domain.entities import Service, ServiceCategory, generate_id, utc_now
from infrastructure.repositories import MongoServiceRepository
from infrastructure.external import get_revel_service
from infrastructure.cache import CacheService

logger = logging.getLogger(__name__)


class ServiceUseCase:
    """Service management use cases"""
    
    def __init__(
        self,
        service_repo: MongoServiceRepository,
        cache: Optional[CacheService] = None
    ):
        self.service_repo = service_repo
        self.cache = cache
        self.revel_service = get_revel_service()
    
    async def create_service(
        self,
        name: str,
        description: str,
        category: ServiceCategory,
        duration_minutes: int,
        price: float,
        discount_price: Optional[float] = None,
        image_url: Optional[str] = None,
        is_featured: bool = False,
        max_capacity: int = 1,
        revel_product_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new service"""
        # Validate with REVEL if product ID provided
        if revel_product_id:
            revel_product = await self.revel_service.validate_service(revel_product_id)
            if not revel_product:
                logger.warning(f"REVEL product {revel_product_id} not found, continuing anyway")
        
        service = Service(
            service_id=generate_id(),
            name=name,
            description=description,
            category=category,
            duration_minutes=duration_minutes,
            price=price,
            discount_price=discount_price,
            image_url=image_url,
            is_featured=is_featured,
            is_active=True,
            max_capacity=max_capacity,
            revel_product_id=revel_product_id
        )
        
        service_dict = service.model_dump()
        service_dict["created_at"] = service_dict["created_at"].isoformat()
        service_dict["updated_at"] = service_dict["updated_at"].isoformat()
        service_dict["category"] = category.value
        
        await self.service_repo.create(service_dict)
        
        # Invalidate cache
        if self.cache:
            await self.cache.delete(CacheService.services_key())
            await self.cache.delete(CacheService.featured_services_key())
        
        logger.info(f"Service created: {service.service_id} - {name}")
        return service_dict
    
    async def update_service(
        self,
        service_id: str,
        **updates
    ) -> Dict[str, Any]:
        """Update a service"""
        service = await self.service_repo.get_by_id(service_id)
        if not service:
            raise ValueError("Service not found")
        
        # Convert category enum if present
        if "category" in updates and updates["category"]:
            updates["category"] = updates["category"].value if hasattr(updates["category"], 'value') else updates["category"]
        
        # Filter out None values
        updates = {k: v for k, v in updates.items() if v is not None}
        
        await self.service_repo.update(service_id, updates)
        
        # Invalidate cache
        if self.cache:
            await self.cache.delete(CacheService.services_key())
            await self.cache.delete(CacheService.featured_services_key())
            await self.cache.delete(CacheService.service_key(service_id))
        
        logger.info(f"Service updated: {service_id}")
        return await self.service_repo.get_by_id(service_id)
    
    async def get_service_by_id(self, service_id: str) -> Dict[str, Any]:
        """Get a service by ID"""
        # Check cache first
        if self.cache:
            cached = await self.cache.get(CacheService.service_key(service_id))
            if cached:
                return cached
        
        service = await self.service_repo.get_by_id(service_id)
        if not service:
            raise ValueError("Service not found")
        
        # Cache the result
        if self.cache:
            await self.cache.set(CacheService.service_key(service_id), service, ttl=300)
        
        return service
    
    async def get_all_services(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Get all services"""
        # Check cache first
        if self.cache:
            cached = await self.cache.get(CacheService.services_key())
            if cached:
                if active_only:
                    return [s for s in cached if s.get("is_active")]
                return cached
        
        if active_only:
            services = await self.service_repo.get_active()
        else:
            services = await self.service_repo.list_all()
        
        # Cache the result
        if self.cache:
            await self.cache.set(CacheService.services_key(), services, ttl=300)
        
        return services
    
    async def get_featured_services(self) -> List[Dict[str, Any]]:
        """Get featured services"""
        # Check cache first
        if self.cache:
            cached = await self.cache.get(CacheService.featured_services_key())
            if cached:
                return cached
        
        services = await self.service_repo.get_featured()
        
        # Cache the result
        if self.cache:
            await self.cache.set(CacheService.featured_services_key(), services, ttl=300)
        
        return services
    
    async def get_services_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Get services by category"""
        return await self.service_repo.get_by_category(category)
    
    async def delete_service(self, service_id: str) -> bool:
        """Soft delete a service (set is_active to False)"""
        service = await self.service_repo.get_by_id(service_id)
        if not service:
            raise ValueError("Service not found")
        
        await self.service_repo.update(service_id, {"is_active": False})
        
        # Invalidate cache
        if self.cache:
            await self.cache.delete(CacheService.services_key())
            await self.cache.delete(CacheService.featured_services_key())
            await self.cache.delete(CacheService.service_key(service_id))
        
        logger.info(f"Service deactivated: {service_id}")
        return True
    
    async def sync_with_revel(self) -> Dict[str, Any]:
        """Sync services with REVEL POS"""
        revel_products = await self.revel_service.get_all_products()
        
        synced = 0
        for product in revel_products:
            # Check if service exists with this REVEL ID
            existing = await self.service_repo.collection.find_one(
                {"revel_product_id": product["product_id"]},
                {"_id": 0}
            )
            
            if existing:
                # Update price if changed
                if existing["price"] != product["price"]:
                    await self.service_repo.update(existing["service_id"], {
                        "price": product["price"]
                    })
                    synced += 1
        
        logger.info(f"REVEL sync complete: {synced} services updated")
        return {"synced": synced, "total_revel_products": len(revel_products)}
