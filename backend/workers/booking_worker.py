"""
Legacy Celery tasks for booking + Revel were removed.

Bookings are OTC-only (no Revel). Store/e-commerce uses Revel via `store_routes` + `RevelService`.
This module is kept so older Celery worker deployments that reference
`workers.booking_worker` do not fail on import; it registers no tasks.
"""
