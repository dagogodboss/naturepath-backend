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
    
    logger.info("Application startup complete")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await Database.disconnect()
    if cache:
        await cache.disconnect()
    logger.info("Application shutdown complete")

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
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
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
