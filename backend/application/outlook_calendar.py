"""Pure availability helpers shared by Outlook sync and booking selection."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _minutes(value: str) -> int:
    hour, minute = str(value).split(":", 1)
    return int(hour) * 60 + int(minute[:2])


def subtract_busy_intervals(
    available: Iterable[Dict[str, Any]],
    outlook_events: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Remove app slots that overlap a blocking Outlook event."""
    blocking = []
    for event in outlook_events:
        if event.get("is_cancelled") is True:
            continue
        if str(event.get("show_as") or "busy").lower() == "free":
            continue
        blocking.append((_minutes(event["start_time"]), _minutes(event["end_time"])))

    result: List[Dict[str, Any]] = []
    for slot in available:
        start = _minutes(slot["start_time"])
        end = _minutes(slot["end_time"])
        if any(start < busy_end and end > busy_start for busy_start, busy_end in blocking):
            continue
        result.append(slot)
    return result
