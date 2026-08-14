from infrastructure.external.microsoft_graph import (
    MicrosoftGraphClient,
    OutlookTokenCipher,
    event_to_busy_interval,
    event_to_busy_intervals,
)


def test_authorization_url_requests_profile_calendar_and_offline_access():
    client = MicrosoftGraphClient(
        client_id="client-id",
        client_secret="secret",
        tenant_id="common",
        redirect_uri="https://api.example.com/callback",
    )
    url = client.authorization_url("signed-state")
    assert "User.Read" in url
    assert "Calendars.Read" in url
    assert "offline_access" in url
    assert "state=signed-state" in url


def test_refresh_tokens_are_encrypted_at_rest():
    cipher = OutlookTokenCipher("application-secret")
    encrypted = cipher.encrypt("refresh-token-value")
    assert encrypted != "refresh-token-value"
    assert cipher.decrypt(encrypted) == "refresh-token-value"


def test_graph_event_is_normalized_to_clinic_local_busy_interval():
    event = {
        "id": "event-1",
        "showAs": "busy",
        "isCancelled": False,
        "start": {"dateTime": "2026-08-11T15:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-08-11T16:00:00.0000000", "timeZone": "UTC"},
    }
    interval = event_to_busy_interval(event, "Africa/Lagos")
    assert interval["event_id"] == "event-1"
    assert interval["date"] == "2026-08-11"
    assert interval["start_time"] == "16:00"
    assert interval["end_time"] == "17:00"
    assert interval["show_as"] == "busy"
    assert interval["is_cancelled"] is False
    assert interval["starts_at"].startswith("2026-08-11T16:00:00")
    assert interval["ends_at"].startswith("2026-08-11T17:00:00")


def test_multi_day_graph_event_blocks_each_clinic_calendar_day():
    event = {
        "id": "event-all-day",
        "showAs": "oof",
        "isCancelled": False,
        "start": {"dateTime": "2026-08-11T00:00:00", "timeZone": "Africa/Lagos"},
        "end": {"dateTime": "2026-08-13T00:00:00", "timeZone": "Africa/Lagos"},
    }

    intervals = event_to_busy_intervals(event, "Africa/Lagos")

    assert [(row["date"], row["start_time"], row["end_time"]) for row in intervals] == [
        ("2026-08-11", "00:00", "24:00"),
        ("2026-08-12", "00:00", "24:00"),
    ]
