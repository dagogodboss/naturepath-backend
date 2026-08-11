"""Unit tests for reminder offsets (C3) and PWA standalone refresh TTL (E)."""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from jose import jwt

from application.use_cases.auth_use_case import AuthUseCase
from core.config import settings
from workers.notification_worker import REMINDER_OFFSETS


def test_reminder_offsets_match_po_spec():
    assert REMINDER_OFFSETS == {"d3": 3, "d1": 1, "d0": 0}


def test_standalone_refresh_ttl_is_ninety_days():
    assert settings.refresh_token_expire_days_standalone == 90
    assert settings.refresh_token_expire_days == 7


def test_create_refresh_token_marks_standalone_and_longer_exp():
    uc = AuthUseCase(user_repo=MagicMock())
    with patch.object(settings, "jwt_secret_key", "test-secret-key-for-plan-suite"):
        token = uc._create_refresh_token({"sub": "u1"}, standalone=True)
        payload = jwt.decode(
            token,
            "test-secret-key-for-plan-suite",
            algorithms=[settings.jwt_algorithm],
        )
        assert payload.get("standalone") is True
        assert payload.get("type") == "refresh"

        normal = uc._create_refresh_token({"sub": "u1"}, standalone=False)
        normal_payload = jwt.decode(
            normal,
            "test-secret-key-for-plan-suite",
            algorithms=[settings.jwt_algorithm],
        )
        # Standalone exp should be ~90d vs ~7d — compare deltas coarsely.
        stand_exp = payload["exp"]
        norm_exp = normal_payload["exp"]
        assert stand_exp - norm_exp > int(timedelta(days=60).total_seconds())
