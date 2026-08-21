"""Review ingestion, sentiment classification, moderation, and alerting."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any, Iterable
import uuid

from pymongo.errors import DuplicateKeyError

POSITIVE_WORDS = {
    "amazing", "best", "excellent", "friendly", "great", "helpful", "kind",
    "knowledgeable", "love", "peaceful", "recommend", "restorative", "wonderful",
}
NEGATIVE_WORDS = {
    "awful", "bad", "disappointed", "horrible", "poor", "rude", "terrible",
    "unhelpful", "worst",
}


def classify_review(rating: int | None, body: str) -> str:
    """Classify deterministically; star rating wins when a provider supplies one."""
    if rating is not None:
        if rating >= 4:
            return "positive"
        if rating <= 2:
            return "negative"
        return "neutral"
    words = {word.strip(".,!?;:()[]\"").lower() for word in body.split()}
    score = len(words & POSITIVE_WORDS) - len(words & NEGATIVE_WORDS)
    if score > 0:
        return "positive"
    if score < 0:
        return "negative"
    return "neutral"


def _clean_item(item: dict[str, Any]) -> dict[str, Any]:
    source = str(item.get("source") or "manual").strip().lower()
    source_review_id = str(item.get("source_review_id") or "").strip()
    author_name = str(item.get("author_name") or "Guest").strip()[:120]
    body = str(item.get("body") or "").strip()[:4000]
    rating_value = item.get("rating")
    rating = int(rating_value) if rating_value not in (None, "") else None
    if rating is not None and not 1 <= rating <= 5:
        raise ValueError("Review ratings must be between 1 and 5")
    if not source_review_id or not body:
        raise ValueError("Each review requires source_review_id and body")
    return {
        "source": source,
        "source_review_id": source_review_id,
        "author_name": author_name or "Guest",
        "rating": rating,
        "body": body,
        "source_url": str(item.get("source_url") or "").strip()[:1000] or None,
        "source_created_at": item.get("source_created_at") or item.get("created_at"),
    }


async def import_reviews(db, items: Iterable[dict[str, Any]], *, notify: bool = True) -> dict[str, int]:
    now = datetime.now(timezone.utc).isoformat()
    counts = {"created": 0, "updated": 0, "negative": 0}
    for raw in items:
        item = _clean_item(raw)
        classification = classify_review(item["rating"], item["body"])
        existing = await db.business_reviews.find_one(
            {"source": item["source"], "source_review_id": item["source_review_id"]},
            {"_id": 0},
        )
        review_id = existing.get("review_id") if existing else str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"naturalpath:review:{item['source']}:{item['source_review_id']}",
            )
        )
        document = {
            **item,
            "review_id": review_id,
            "classification": classification,
            "updated_at": now,
        }
        if not existing:
            document.update(
                {
                    "moderation_status": "pending" if classification == "positive" else "hidden",
                    "alert_sent": False,
                    "imported_at": now,
                }
            )
        review_filter = {
            "source": item["source"],
            "source_review_id": item["source_review_id"],
        }
        try:
            await db.business_reviews.update_one(
                review_filter,
                {"$set": document, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
        except DuplicateKeyError:
            # Another instance won the first-import race; update that row.
            await db.business_reviews.update_one(review_filter, {"$set": document})
        counts["updated" if existing else "created"] += 1

        if classification == "negative" and not (existing or {}).get("alert_sent"):
            counts["negative"] += 1
            if notify:
                from core.config import settings
                from workers.notification_worker import send_generic_email

                recipient = settings.review_alert_email or settings.ops_email
                if recipient:
                    subject = f"Negative {item['source'].title()} review needs attention"
                    html = (
                        "<h2>New negative review</h2>"
                        f"<p><strong>Source:</strong> {escape(item['source'].title())}</p>"
                        f"<p><strong>Reviewer:</strong> {escape(item['author_name'])}</p>"
                        f"<p><strong>Rating:</strong> {escape(str(item['rating'] or 'Not provided'))}</p>"
                        f"<p>{escape(item['body'])}</p>"
                    )
                    send_generic_email.delay(recipient, subject, html, item["body"])
                    await db.business_reviews.update_one(
                        {"review_id": review_id},
                        {"$set": {"alert_sent": True, "alerted_at": now}},
                    )
    return counts


async def ensure_default_testimonials(db) -> None:
    """One-time migration from the former frontend constants into MongoDB."""
    if await db.business_reviews.count_documents({"source": "legacy"}) >= 6:
        return
    testimonials = [
        ("kylie-nicole-neuville", "Kylie Nicole Neuville", "Can't recommend enough! I felt heard, supported, and given natural options that made sense for me."),
        ("terri-j-dauzat", "Terri J. Dauzat", "It's always a treat to visit the store! So much knowledge and tips. A visit to the salt room is a must!"),
        ("kathryn-hernandez-denais", "Kathryn Hernandez Denais", "If you're in need of truly natural products, The Natural Path is the place to go. They have an excellent selection."),
        ("annalisha-arcides", "Annalisha Arcides", "Nichole and Kristin take the best care of their customers and take time to get to know us. I love this place."),
        ("claire-clement", "Claire Clement", "Wonderful customer service! Always willing to go above and beyond and answer any question."),
        ("claire-steel", "Claire Steel", "The staff is amazing, kind, and compassionate. The Natural Path can help with all your natural needs."),
    ]
    await import_reviews(
        db,
        [
            {
                "source": "legacy",
                "source_review_id": review_id,
                "author_name": author,
                "rating": 5,
                "body": body,
            }
            for review_id, author, body in testimonials
        ],
        notify=False,
    )
    await db.business_reviews.update_many(
        {"source": "legacy", "classification": "positive"},
        {"$set": {"moderation_status": "approved"}},
    )
