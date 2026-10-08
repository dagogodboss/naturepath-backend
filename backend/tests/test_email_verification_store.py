from datetime import datetime, timedelta, timezone

import pytest

from application.email_verification import EmailVerificationStore


class FakeCollection:
    def __init__(self):
        self.docs = {}

    async def update_one(self, query, update, upsert=False):
        email = query["email"]
        self.docs[email] = dict(update["$set"])

    async def find_one(self, query):
        return self.docs.get(query["email"])

    async def delete_one(self, query):
        self.docs.pop(query["email"], None)

    async def find_one_and_delete(self, query):
        row = self.docs.get(query["email"])
        if not row or row.get("code_hash") != query.get("code_hash"):
            return None
        return self.docs.pop(query["email"])

    async def find_one_and_update(self, query, update, return_document=None):
        del return_document
        row = self.docs.get(query["email"])
        if not row or row.get("code_hash") != query.get("code_hash"):
            return None
        for field, amount in (update.get("$inc") or {}).items():
            row[field] = int(row.get(field) or 0) + int(amount)
        if "$set" in update:
            row.update(update["$set"])
        return dict(row)


@pytest.mark.asyncio
async def test_issue_and_consume_normalizes_email_and_never_stores_plain_code():
    collection = FakeCollection()
    store = EmailVerificationStore(collection, secret="test-secret")
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)

    await store.issue("  Person@Example.COM ", "004201", now=now)

    saved = collection.docs["person@example.com"]
    assert saved["code_hash"] != "004201"
    assert "code" not in saved
    assert await store.consume("person@example.com", "004201", now=now) is True
    assert collection.docs == {}


@pytest.mark.asyncio
async def test_wrong_code_does_not_consume_valid_challenge():
    collection = FakeCollection()
    store = EmailVerificationStore(collection, secret="test-secret")
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    await store.issue("person@example.com", "123456", now=now)

    assert await store.consume("person@example.com", "999999", now=now) is False
    assert "person@example.com" in collection.docs
    assert await store.consume("person@example.com", "123456", now=now) is True


@pytest.mark.asyncio
async def test_expired_code_is_rejected_and_deleted():
    collection = FakeCollection()
    store = EmailVerificationStore(collection, secret="test-secret", ttl_seconds=60)
    issued = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    await store.issue("person@example.com", "123456", now=issued)

    assert await store.consume(
        "person@example.com",
        "123456",
        now=issued + timedelta(seconds=61),
    ) is False
    assert collection.docs == {}


@pytest.mark.asyncio
async def test_mongo_naive_utc_expiry_is_supported():
    collection = FakeCollection()
    store = EmailVerificationStore(collection, secret="test-secret")
    issued = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    await store.issue("person@example.com", "123456", now=issued)
    collection.docs["person@example.com"]["expires_at"] = collection.docs[
        "person@example.com"
    ]["expires_at"].replace(tzinfo=None)

    assert await store.consume("person@example.com", "123456", now=issued) is True


@pytest.mark.asyncio
async def test_wrong_codes_exhaust_the_challenge_budget():
    collection = FakeCollection()
    store = EmailVerificationStore(collection, secret="test-secret", max_attempts=3)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    await store.issue("person@example.com", "123456", now=now)

    assert await store.consume("person@example.com", "000000", now=now) is False
    assert await store.consume("person@example.com", "000001", now=now) is False
    assert "person@example.com" in collection.docs
    assert await store.consume("person@example.com", "000002", now=now) is False
    assert collection.docs == {}
    assert await store.consume("person@example.com", "123456", now=now) is False


@pytest.mark.asyncio
async def test_replacement_challenge_resets_only_its_own_attempt_budget():
    collection = FakeCollection()
    store = EmailVerificationStore(collection, secret="test-secret", max_attempts=2)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    await store.issue("person@example.com", "111111", now=now)
    assert await store.consume("person@example.com", "000000", now=now) is False

    await store.issue("person@example.com", "222222", now=now)
    assert collection.docs["person@example.com"]["failed_attempts"] == 0
    assert await store.consume("person@example.com", "222222", now=now) is True
