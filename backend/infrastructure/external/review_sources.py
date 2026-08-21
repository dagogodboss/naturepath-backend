"""Official provider adapters for business review ingestion."""

from __future__ import annotations

from typing import Any

import httpx

from core.config import settings


GOOGLE_STAR_RATINGS = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
}


async def fetch_google_business_reviews() -> list[dict[str, Any]]:
    if not all(
        [settings.google_business_profile_access_token, settings.google_business_account_id,
         settings.google_business_location_id]
    ):
        return []
    url = (
        "https://mybusiness.googleapis.com/v4/accounts/"
        f"{settings.google_business_account_id}/locations/{settings.google_business_location_id}/reviews"
    )
    headers = {"Authorization": f"Bearer {settings.google_business_profile_access_token}"}
    items: list[dict[str, Any]] = []
    params: dict[str, Any] | None = {"pageSize": 50, "orderBy": "updateTime desc"}
    async with httpx.AsyncClient(timeout=30) as client:
        while url:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            payload = response.json()
            for review in payload.get("reviews") or []:
                items.append(
                    {
                        "source": "google",
                        "source_review_id": review.get("reviewId"),
                        "author_name": (review.get("reviewer") or {}).get("displayName") or "Google reviewer",
                        "rating": GOOGLE_STAR_RATINGS.get(review.get("starRating")),
                        "body": review.get("comment") or "",
                        "source_created_at": review.get("createTime"),
                    }
                )
            token = payload.get("nextPageToken")
            params = {"pageToken": token, "pageSize": 50} if token else None
            if not token:
                url = ""
    return [item for item in items if item["source_review_id"] and item["body"]]


async def fetch_yelp_reviews() -> list[dict[str, Any]]:
    if not settings.yelp_api_key or not settings.yelp_business_id:
        return []
    url = f"https://api.yelp.com/v3/businesses/{settings.yelp_business_id}/reviews"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {settings.yelp_api_key}"})
        response.raise_for_status()
    return [
        {
            "source": "yelp",
            "source_review_id": review.get("id"),
            "author_name": (review.get("user") or {}).get("name") or "Yelp reviewer",
            "rating": review.get("rating"),
            "body": review.get("text") or "",
            "source_url": review.get("url"),
            "source_created_at": review.get("time_created"),
        }
        for review in response.json().get("reviews") or []
        if review.get("id") and review.get("text")
    ]


async def fetch_all_configured_reviews() -> list[dict[str, Any]]:
    return [*(await fetch_google_business_reviews()), *(await fetch_yelp_reviews())]
