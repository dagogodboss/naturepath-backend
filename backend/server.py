"""
The Natural Path Spa Management System
Production-Grade FastAPI Backend with DDD/Clean Architecture

Main application entry point
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Import infrastructure
from infrastructure.database import Database
from infrastructure.cache import get_cache_service

# Import presentation layer
from presentation import (
    auth_router,
    user_router,
    service_router,
    practitioner_router,
    booking_router,
    admin_router,
    webhook_router,
    availability_websocket_handler,
    user_notification_websocket_handler
)

# Import core config
from core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown events"""
    # Startup
    logger.info("Starting The Natural Path Spa Management System...")
    
    # Connect to MongoDB
    await Database.connect()
    
    # Initialize cache
    cache = await get_cache_service()
    logger.info("Cache service initialized")
    
    # Seed initial data if needed
    await seed_initial_data()
    
    logger.info("Application startup complete")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await Database.disconnect()
    if cache:
        await cache.disconnect()
    logger.info("Application shutdown complete")


async def seed_initial_data():
    """Seed initial data for the application"""
    from infrastructure.database import get_database
    from domain.entities import generate_id, utc_now, UserRole, ServiceCategory
    from passlib.context import CryptContext
    
    db = get_database()
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    # Check if admin exists
    admin = await db.users.find_one({"email": "admin@thenaturalpath.com"})
    if not admin:
        # Create admin user
        admin_id = generate_id()
        admin_user = {
            "user_id": admin_id,
            "email": "admin@thenaturalpath.com",
            "password_hash": pwd_context.hash("admin123"),
            "first_name": "Admin",
            "last_name": "User",
            "phone": "+1234567890",
            "role": "admin",
            "is_active": True,
            "is_verified": True,
            "created_at": utc_now().isoformat(),
            "updated_at": utc_now().isoformat()
        }
        await db.users.insert_one(admin_user)
        logger.info("Admin user created: admin@thenaturalpath.com / admin123")
    
    # Check if services exist
    services_count = await db.services.count_documents({})
    if services_count == 0:
        # Create sample services
        services = [
            {
                "service_id": generate_id(),
                "name": "Swedish Massage",
                "description": "A gentle, relaxing massage that uses long strokes, kneading, and circular movements to help relax and energize you.",
                "category": "massage",
                "duration_minutes": 60,
                "price": 120.00,
                "discount_price": None,
                "image_url": "https://images.unsplash.com/photo-1544161515-4ab6ce6db874?w=800",
                "is_featured": True,
                "is_active": True,
                "max_capacity": 1,
                "revel_product_id": "revel_svc_001",
                "created_at": utc_now().isoformat(),
                "updated_at": utc_now().isoformat()
            },
            {
                "service_id": generate_id(),
                "name": "Deep Tissue Massage",
                "description": "Targets the deeper layers of muscle and connective tissue using slower, more forceful strokes.",
                "category": "massage",
                "duration_minutes": 75,
                "price": 150.00,
                "discount_price": None,
                "image_url": "https://images.unsplash.com/photo-1519823551278-64ac92734fb1?w=800",
                "is_featured": True,
                "is_active": True,
                "max_capacity": 1,
                "revel_product_id": "revel_svc_002",
                "created_at": utc_now().isoformat(),
                "updated_at": utc_now().isoformat()
            },
            {
                "service_id": generate_id(),
                "name": "Hot Stone Massage",
                "description": "Smooth, heated stones are placed on specific points on your body and used as massage tools.",
                "category": "massage",
                "duration_minutes": 90,
                "price": 175.00,
                "discount_price": 160.00,
                "image_url": "https://images.unsplash.com/photo-1600334089648-b0d9d3028eb2?w=800",
                "is_featured": True,
                "is_active": True,
                "max_capacity": 1,
                "revel_product_id": "revel_svc_003",
                "created_at": utc_now().isoformat(),
                "updated_at": utc_now().isoformat()
            },
            {
                "service_id": generate_id(),
                "name": "Aromatherapy Facial",
                "description": "A rejuvenating facial treatment using essential oils to nourish and revitalize your skin.",
                "category": "facial",
                "duration_minutes": 60,
                "price": 95.00,
                "discount_price": None,
                "image_url": "https://images.unsplash.com/photo-1570172619644-dfd03ed5d881?w=800",
                "is_featured": False,
                "is_active": True,
                "max_capacity": 1,
                "revel_product_id": "revel_svc_004",
                "created_at": utc_now().isoformat(),
                "updated_at": utc_now().isoformat()
            },
            {
                "service_id": generate_id(),
                "name": "Anti-Aging Facial",
                "description": "Advanced facial treatment targeting fine lines, wrinkles, and signs of aging.",
                "category": "facial",
                "duration_minutes": 75,
                "price": 145.00,
                "discount_price": None,
                "image_url": "https://images.unsplash.com/photo-1512290923902-8a9f81dc236c?w=800",
                "is_featured": False,
                "is_active": True,
                "max_capacity": 1,
                "revel_product_id": "revel_svc_005",
                "created_at": utc_now().isoformat(),
                "updated_at": utc_now().isoformat()
            },
            {
                "service_id": generate_id(),
                "name": "Body Wrap Treatment",
                "description": "A detoxifying body treatment that helps eliminate toxins and hydrate your skin.",
                "category": "body_treatment",
                "duration_minutes": 90,
                "price": 130.00,
                "discount_price": None,
                "image_url": "https://images.unsplash.com/photo-1540555700478-4be289fbecef?w=800",
                "is_featured": False,
                "is_active": True,
                "max_capacity": 1,
                "revel_product_id": "revel_svc_006",
                "created_at": utc_now().isoformat(),
                "updated_at": utc_now().isoformat()
            },
            {
                "service_id": generate_id(),
                "name": "Wellness Consultation",
                "description": "Personalized wellness consultation to create a holistic health plan tailored to your needs.",
                "category": "wellness",
                "duration_minutes": 45,
                "price": 75.00,
                "discount_price": None,
                "image_url": "https://images.unsplash.com/photo-1506126613408-eca07ce68773?w=800",
                "is_featured": False,
                "is_active": True,
                "max_capacity": 1,
                "revel_product_id": "revel_svc_007",
                "created_at": utc_now().isoformat(),
                "updated_at": utc_now().isoformat()
            },
            {
                "service_id": generate_id(),
                "name": "Holistic Healing Session",
                "description": "A comprehensive healing session combining massage, energy work, and aromatherapy.",
                "category": "holistic",
                "duration_minutes": 120,
                "price": 200.00,
                "discount_price": 180.00,
                "image_url": "https://images.unsplash.com/photo-1515377905703-c4788e51af15?w=800",
                "is_featured": True,
                "is_active": True,
                "max_capacity": 1,
                "revel_product_id": "revel_svc_008",
                "created_at": utc_now().isoformat(),
                "updated_at": utc_now().isoformat()
            }
        ]
        
        await db.services.insert_many(services)
        logger.info(f"Created {len(services)} sample services")
        
        # Create sample practitioner user
        pract_user_id = generate_id()
        pract_user = {
            "user_id": pract_user_id,
            "email": "sarah@thenaturalpath.com",
            "password_hash": pwd_context.hash("practitioner123"),
            "first_name": "Sarah",
            "last_name": "Chen",
            "phone": "+1234567891",
            "role": "practitioner",
            "is_active": True,
            "is_verified": True,
            "profile_image_url": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=400",
            "created_at": utc_now().isoformat(),
            "updated_at": utc_now().isoformat()
        }
        await db.users.insert_one(pract_user)
        
        # Create practitioner profile
        practitioner = {
            "practitioner_id": generate_id(),
            "user_id": pract_user_id,
            "bio": "Sarah Chen is a certified massage therapist and holistic wellness practitioner with over 10 years of experience. Her approach combines Eastern and Western healing traditions to create personalized treatments that address both physical and emotional well-being.",
            "philosophy": "I believe in treating the whole person, not just the symptoms. My goal is to help each client achieve balance and harmony in their body, mind, and spirit through the healing power of touch and natural therapies.",
            "specialties": [
                {"name": "Swedish Massage", "description": "Relaxation techniques", "years_experience": 10},
                {"name": "Deep Tissue", "description": "Therapeutic pressure work", "years_experience": 8},
                {"name": "Aromatherapy", "description": "Essential oil treatments", "years_experience": 6}
            ],
            "certifications": [
                "Licensed Massage Therapist (LMT)",
                "Certified Aromatherapist",
                "Reiki Master Level III"
            ],
            "services": [s["service_id"] for s in services[:4]],
            "availability": [
                {"day_of_week": 0, "start_time": "09:00", "end_time": "18:00", "is_available": True},
                {"day_of_week": 1, "start_time": "09:00", "end_time": "18:00", "is_available": True},
                {"day_of_week": 2, "start_time": "09:00", "end_time": "18:00", "is_available": True},
                {"day_of_week": 3, "start_time": "09:00", "end_time": "18:00", "is_available": True},
                {"day_of_week": 4, "start_time": "09:00", "end_time": "17:00", "is_available": True},
                {"day_of_week": 5, "start_time": "10:00", "end_time": "15:00", "is_available": True},
                {"day_of_week": 6, "start_time": "00:00", "end_time": "00:00", "is_available": False}
            ],
            "hourly_rate": 120.00,
            "is_featured": True,
            "rating": 4.9,
            "total_reviews": 127,
            "created_at": utc_now().isoformat(),
            "updated_at": utc_now().isoformat()
        }
        await db.practitioners.insert_one(practitioner)
        logger.info("Created sample practitioner: sarah@thenaturalpath.com / practitioner123")
        
        # Create second practitioner
        pract_user_id2 = generate_id()
        pract_user2 = {
            "user_id": pract_user_id2,
            "email": "michael@thenaturalpath.com",
            "password_hash": pwd_context.hash("practitioner123"),
            "first_name": "Michael",
            "last_name": "Roberts",
            "phone": "+1234567892",
            "role": "practitioner",
            "is_active": True,
            "is_verified": True,
            "profile_image_url": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400",
            "created_at": utc_now().isoformat(),
            "updated_at": utc_now().isoformat()
        }
        await db.users.insert_one(pract_user2)
        
        practitioner2 = {
            "practitioner_id": generate_id(),
            "user_id": pract_user_id2,
            "bio": "Michael Roberts specializes in therapeutic deep tissue massage and sports rehabilitation. With a background in physical therapy, he brings a unique clinical perspective to wellness treatments.",
            "philosophy": "Movement is life. My practice focuses on restoring mobility, relieving chronic pain, and helping clients return to their active lifestyles.",
            "specialties": [
                {"name": "Deep Tissue Massage", "description": "Advanced techniques", "years_experience": 12},
                {"name": "Sports Massage", "description": "Athletic recovery", "years_experience": 10},
                {"name": "Myofascial Release", "description": "Connective tissue work", "years_experience": 8}
            ],
            "certifications": [
                "Licensed Massage Therapist (LMT)",
                "Certified Sports Massage Therapist",
                "Physical Therapy Assistant (PTA)"
            ],
            "services": [s["service_id"] for s in services[1:6]],
            "availability": [
                {"day_of_week": 0, "start_time": "10:00", "end_time": "19:00", "is_available": True},
                {"day_of_week": 1, "start_time": "10:00", "end_time": "19:00", "is_available": True},
                {"day_of_week": 2, "start_time": "10:00", "end_time": "19:00", "is_available": True},
                {"day_of_week": 3, "start_time": "10:00", "end_time": "19:00", "is_available": True},
                {"day_of_week": 4, "start_time": "10:00", "end_time": "19:00", "is_available": True},
                {"day_of_week": 5, "start_time": "00:00", "end_time": "00:00", "is_available": False},
                {"day_of_week": 6, "start_time": "11:00", "end_time": "16:00", "is_available": True}
            ],
            "hourly_rate": 130.00,
            "is_featured": True,
            "rating": 4.8,
            "total_reviews": 89,
            "created_at": utc_now().isoformat(),
            "updated_at": utc_now().isoformat()
        }
        await db.practitioners.insert_one(practitioner2)
        logger.info("Created sample practitioner: michael@thenaturalpath.com / practitioner123")


# Create FastAPI application
app = FastAPI(
    title="The Natural Path Spa Management System",
    description="""
    Production-grade spa management API with REVEL POS integration.
    
    ## Features
    - Customer booking journey
    - Practitioner profiles and availability
    - Admin management dashboard
    - REVEL POS integration for payments and bookings
    - Real-time availability updates via WebSocket
    - Background task processing with Celery
    
    ## Architecture
    - Domain-Driven Design (DDD)
    - Clean Architecture
    - Event-Driven Design
    - Async-first for high concurrency
    """,
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


# Include API routers
app.include_router(auth_router, prefix="/api")
app.include_router(user_router, prefix="/api")
app.include_router(service_router, prefix="/api")
app.include_router(practitioner_router, prefix="/api")
app.include_router(booking_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(webhook_router, prefix="/api")


# WebSocket endpoints
@app.websocket("/ws/availability/{practitioner_id}/{date}")
async def websocket_availability(
    websocket: WebSocket,
    practitioner_id: str,
    date: str
):
    """WebSocket endpoint for real-time availability updates"""
    await availability_websocket_handler(websocket, practitioner_id, date)


@app.websocket("/ws/notifications/{user_id}")
async def websocket_notifications(
    websocket: WebSocket,
    user_id: str
):
    """WebSocket endpoint for user notifications"""
    await user_notification_websocket_handler(websocket, user_id)


# Health check endpoint
@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "The Natural Path Spa API",
        "version": "1.0.0"
    }


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "service": "The Natural Path Spa Management System",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
