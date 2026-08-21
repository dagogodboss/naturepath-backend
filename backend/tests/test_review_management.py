from application.review_management import classify_review


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
