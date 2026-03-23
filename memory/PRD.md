# The Natural Path Spa Management System - PRD

## Original Problem Statement
Build a production-grade backend for "The Natural Path Spa Management System" with:
- Full FastAPI backend with DDD/Clean Architecture
- MongoDB database
- Mock REVEL POS integration for payments/bookings
- Celery + Redis for background tasks
- WebSocket for real-time availability
- Resend email + Twilio SMS notifications
- React TypeScript SDK for frontend integration

## Architecture

### Backend Structure (DDD/Clean Architecture)
```
/app/backend/
├── core/                    # Configuration
├── domain/                  # Domain Layer
│   ├── entities/           # Business entities
│   ├── events/             # Domain events
│   ├── repositories/       # Repository interfaces
│   └── services/           # Domain services
├── application/            # Application Layer
│   ├── use_cases/          # Business logic
│   └── dto/                # Data transfer objects
├── infrastructure/         # Infrastructure Layer
│   ├── database/           # MongoDB connection
│   ├── repositories/       # Repository implementations
│   ├── external/           # External services (REVEL, Email, SMS)
│   ├── cache/              # Redis cache
│   └── queue/              # Celery configuration
├── presentation/           # Presentation Layer
│   ├── api/                # FastAPI routers
│   ├── dependencies/       # DI dependencies
│   └── websockets/         # WebSocket handlers
└── workers/                # Celery background workers
```

### SDK Structure
```
/app/sdk/
├── src/
│   ├── api/                # API client & endpoints
│   ├── hooks/              # React Query hooks
│   ├── providers/          # NaturalPathProvider
│   ├── types/              # TypeScript types
│   ├── utils/              # Utility functions
│   └── websocket/          # WebSocket manager
├── docs/                   # Documentation
└── examples/               # Usage examples
```

## What's Been Implemented (March 2026)

### Backend (100% Complete)
- [x] FastAPI server with async endpoints
- [x] MongoDB database with proper indexes
- [x] JWT authentication (access + refresh tokens)
- [x] Complete CRUD for Services, Practitioners, Bookings
- [x] Multi-step booking flow (initiate → lock → confirm)
- [x] Mock REVEL POS integration
- [x] WebSocket for real-time availability
- [x] Celery workers for background tasks
- [x] Email service (Resend) - integrated
- [x] SMS service (Twilio) - integrated
- [x] Admin dashboard endpoints
- [x] Booking analytics endpoints
- [x] Seed data for testing

### SDK (100% Complete)
- [x] TypeScript types for all entities
- [x] React Query hooks for all endpoints
- [x] Authentication hooks (useAuth)
- [x] Service hooks (useServices, useService)
- [x] Practitioner hooks (usePractitioners, useAvailability)
- [x] Booking hooks (useBookingFlow, useUserBookings)
- [x] Admin hooks (useAdminStats, useBookingAnalytics)
- [x] WebSocket hooks (useRealtimeAvailability)
- [x] NaturalPathProvider component
- [x] Full documentation (README, Integration Guide)
- [x] Usage examples

## API Endpoints

### Auth
- POST /api/auth/register
- POST /api/auth/login
- POST /api/auth/refresh

### Services
- GET /api/services
- GET /api/services/featured
- GET /api/services/{id}
- POST /api/services (admin)
- PATCH /api/services/{id} (admin)
- DELETE /api/services/{id} (admin)

### Practitioners
- GET /api/practitioners
- GET /api/practitioners/featured
- GET /api/practitioners/{id}
- GET /api/practitioners/{id}/availability
- POST /api/practitioners (admin)
- PATCH /api/practitioners/{id}

### Booking
- POST /api/booking/initiate
- POST /api/booking/lock-slot
- POST /api/booking/confirm
- GET /api/booking/{id}
- POST /api/booking/cancel
- GET /api/booking/admin/all (admin)

### User
- GET /api/me
- PATCH /api/me
- GET /api/me/bookings
- GET /api/me/notifications

### Admin
- GET /api/admin/stats
- GET /api/admin/analytics/bookings
- GET /api/admin/customers
- GET /api/admin/users

### WebSocket
- WS /ws/availability/{practitioner_id}/{date}
- WS /ws/notifications/{user_id}

## Test Credentials
- Admin: admin@thenaturalpath.com / admin123
- Practitioner: sarah@thenaturalpath.com / practitioner123
- Practitioner: michael@thenaturalpath.com / practitioner123

## Prioritized Backlog

### P0 (Critical)
- [x] Backend API implementation
- [x] SDK implementation

### P1 (High Priority)
- [ ] Frontend implementation using SDK
- [ ] Production deployment configuration
- [ ] Actual Resend/Twilio API key configuration

### P2 (Medium Priority)
- [ ] Rescheduling functionality
- [ ] Practitioner calendar management UI
- [ ] Customer reviews/ratings

### P3 (Nice to Have)
- [ ] Gift card support
- [ ] Package deals/bundles
- [ ] Loyalty points system
- [ ] Mobile app (React Native)

## Next Tasks
1. Configure actual Resend API key for email notifications
2. Configure actual Twilio credentials for SMS
3. Build frontend using the SDK
4. Deploy to production environment
5. Set up monitoring and logging
