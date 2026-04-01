"""API Routes Package"""
from .auth_routes import router as auth_router
from .user_routes import router as user_router
from .service_routes import router as service_router
from .practitioner_routes import router as practitioner_router
from .booking_routes import router as booking_router
from .admin_routes import router as admin_router
from .webhook_routes import router as webhook_router
from .store_routes import router as store_router

__all__ = [
    "auth_router",
    "user_router",
    "service_router",
    "practitioner_router",
    "booking_router",
    "admin_router",
    "webhook_router",
    "store_router",
]
