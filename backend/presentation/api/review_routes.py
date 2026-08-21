"""Public testimonial and admin review moderation APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from application.review_management import import_reviews
from infrastructure.database import get_database
from presentation.dependencies import get_current_admin


router = APIRouter(tags=["Reviews"])


class ImportedReview(BaseModel):
    source: str = Field(min_length=1, max_length=30)
    source_review_id: str = Field(min_length=1, max_length=200)
    author_name: str = Field(default="Guest", max_length=120)
    rating: int | None = Field(default=None, ge=1, le=5)
    body: str = Field(min_length=1, max_length=4000)
    source_url: str | None = Field(default=None, max_length=1000)
    source_created_at: str | None = None


class ImportRequest(BaseModel):
    items: list[ImportedReview] = Field(min_length=1, max_length=500)


class ModerateRequest(BaseModel):
    status: str


@router.get("/reviews/testimonials", response_model=dict)
async def published_testimonials(
    limit: int = Query(default=20, ge=1, le=50),
    db=Depends(get_database),
):
    rows = await (
        db.business_reviews.find(
            {"classification": "positive", "moderation_status": "approved"},
            {"_id": 0, "alert_sent": 0, "alerted_at": 0},
        )
        .sort([("source_created_at", -1), ("created_at", -1)])
        .limit(limit)
        .to_list(length=limit)
    )
    return {"items": rows, "total": len(rows)}


@router.get("/admin/reviews", response_model=dict)
async def admin_list_reviews(
    status: str | None = None,
    current_admin: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    query: dict[str, Any] = {}
    if status:
        query["moderation_status"] = status
    rows = await (
        db.business_reviews.find(query, {"_id": 0})
        .sort("imported_at", -1)
        .limit(500)
        .to_list(length=500)
    )
    return {"items": rows, "total": len(rows)}


@router.post("/admin/reviews/import", response_model=dict)
async def admin_import_reviews(
    request: ImportRequest,
    current_admin: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    return await import_reviews(db, [item.model_dump() for item in request.items])


@router.post("/admin/reviews/sync", response_model=dict)
async def admin_sync_reviews(current_admin: dict = Depends(get_current_admin)):
    from workers.review_worker import sync_business_reviews

    task = sync_business_reviews.delay()
    return {"queued": True, "task_id": task.id}


@router.patch("/admin/reviews/{review_id}", response_model=dict)
async def admin_moderate_review(
    review_id: str,
    request: ModerateRequest,
    current_admin: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    if request.status not in {"approved", "rejected", "hidden", "pending"}:
        raise HTTPException(status_code=400, detail="Invalid moderation status")
    now = datetime.now(timezone.utc).isoformat()
    result = await db.business_reviews.update_one(
        {"review_id": review_id},
        {"$set": {
            "moderation_status": request.status,
            "moderated_at": now,
            "moderated_by": current_admin.get("user_id"),
            "updated_at": now,
        }},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Review not found")
    return await db.business_reviews.find_one({"review_id": review_id}, {"_id": 0})
