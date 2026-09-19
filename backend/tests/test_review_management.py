from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from application.review_management import classify_review, import_reviews


def test_rating_drives_review_classification():
    assert classify_review(5, "") == "positive"
    assert classify_review(4, "") == "positive"
    assert classify_review(3, "") == "neutral"
    assert classify_review(2, "") == "negative"
    assert classify_review(1, "") == "negative"


def test_text_fallback_classifies_unrated_feedback():
    assert classify_review(None, "Wonderful, kind and helpful staff") == "positive"
    assert classify_review(None, "Terrible and rude experience") == "negative"
    assert classify_review(None, "I visited on Tuesday") == "neutral"


@pytest.mark.asyncio
async def test_negative_review_is_hidden_and_queues_email_alert(monkeypatch):
    collection = SimpleNamespace(
        find_one=AsyncMock(return_value=None),
        update_one=AsyncMock(),
    )
    db = SimpleNamespace(business_reviews=collection)
    monkeypatch.setattr("core.config.settings.review_alert_email", "alerts@example.com")

    with patch("workers.notification_worker.send_generic_email.delay") as enqueue:
        result = await import_reviews(
            db,
            [
                {
                    "source": "google",
                    "source_review_id": "negative-1",
                    "author_name": "Concerned Client",
                    "rating": 1,
                    "body": "A terrible and disappointing visit.",
                }
            ],
        )

    assert result == {"created": 1, "updated": 0, "negative": 1}
    enqueue.assert_called_once()
    recipient, subject, html, text = enqueue.call_args.args
    assert recipient == "alerts@example.com"
    assert "Negative Google review" in subject
    assert "Concerned Client" in html
    assert text == "A terrible and disappointing visit."
    first_document = collection.update_one.await_args_list[0].args[1]["$set"]
    assert first_document["classification"] == "negative"
    assert first_document["moderation_status"] == "hidden"
    assert collection.update_one.await_args_list[1].args[1]["$set"]["alert_sent"] is True


@pytest.mark.asyncio
async def test_positive_review_waits_for_moderation_without_alert():
    collection = SimpleNamespace(
        find_one=AsyncMock(return_value=None),
        update_one=AsyncMock(),
    )
    db = SimpleNamespace(business_reviews=collection)

    with patch("workers.notification_worker.send_generic_email.delay") as enqueue:
        result = await import_reviews(
            db,
            [
                {
                    "source": "facebook",
                    "source_review_id": "positive-1",
                    "author_name": "Happy Client",
                    "rating": 5,
                    "body": "Wonderful, kind and helpful staff.",
                }
            ],
        )

    assert result == {"created": 1, "updated": 0, "negative": 0}
    enqueue.assert_not_called()
    document = collection.update_one.await_args.args[1]["$set"]
    assert document["classification"] == "positive"
    assert document["moderation_status"] == "pending"
