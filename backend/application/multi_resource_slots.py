"""
Per-resource slot engine (Phase 3).

Pure functions. Booking open-dates/slots/confirm import this only through
application.multi_resource_booking when settings.multi_resource_scheduling is
True (default False — legacy practitioner-global path unchanged).

Clinic wall-clock times are America/Chicago (date + HH:MM), matching stored
busy intervals and weekly_hours. No IANA conversion is required for day math.

Occupied span for app bookings:
    [session_start - prep, session_start + session + recovery)
Outlook-imported busy is already full protected time — pass it as busy intervals
as-is (do not add prep/recovery again).

PROVISIONAL (Jonathan): Q3 Discovery last start (occupied ≤ 17:45 → 17:00 when
occupied is 45m, not 17:15); Q4 untagged busy blocks until review; Q7 app
primary for reschedule — see multi_resource_booking / phase-0 docs.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from domain.scheduling_occupation import occupied_minutes

# Clinic-local date/time convention (see Resource.timezone default).
CLINIC_TIMEZONE = "America/Chicago"

Interval = Tuple[int, int]  # [start_minute, end_minute) from midnight
WeeklyHoursRow = Union[Mapping[str, Any], Any]


def minutes_from_hhmm(value: str) -> int:
    """Parse HH:MM (or HH:MM:SS) to minutes from midnight. Accepts 24:00 → 1440."""
    text = str(value).strip()
    if text == "24:00":
        return 24 * 60
    parts = text.split(":")
    if len(parts) < 2:
        raise ValueError(f"invalid time: {value!r}")
    hour = int(parts[0])
    minute = int(parts[1][:2])
    if hour == 24 and minute == 0:
        return 24 * 60
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid time: {value!r}")
    return hour * 60 + minute


def hhmm_from_minutes(total: int) -> str:
    """Format minutes from midnight as HH:MM (24:00 for end-of-day)."""
    if total == 24 * 60:
        return "24:00"
    if total < 0 or total > 24 * 60:
        raise ValueError(f"minutes out of range: {total}")
    return f"{total // 60:02d}:{total % 60:02d}"


def _as_mapping(row: WeeklyHoursRow) -> Mapping[str, Any]:
    if hasattr(row, "model_dump"):
        return row.model_dump()
    if isinstance(row, Mapping):
        return row
    raise TypeError(f"unsupported weekly_hours row: {type(row)!r}")


def _merge_intervals(intervals: Sequence[Interval]) -> List[Interval]:
    if not intervals:
        return []
    ordered = sorted((a, b) for a, b in intervals if b > a)
    if not ordered:
        return []
    merged: List[Interval] = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _intersect_interval_lists(
    left: Sequence[Interval], right: Sequence[Interval]
) -> List[Interval]:
    """Intersection of two merged interval lists."""
    out: List[Interval] = []
    i = j = 0
    a = list(left)
    b = list(right)
    while i < len(a) and j < len(b):
        start = max(a[i][0], b[j][0])
        end = min(a[i][1], b[j][1])
        if start < end:
            out.append((start, end))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def _windows_for_weekday(
    weekly_hours: Sequence[WeeklyHoursRow],
    day_of_week: int,
) -> List[Interval]:
    windows: List[Interval] = []
    for row in weekly_hours:
        data = _as_mapping(row)
        if int(data.get("day_of_week", -1)) != day_of_week:
            continue
        if data.get("is_available", True) is False:
            continue
        start = minutes_from_hhmm(str(data["start_time"]))
        end = minutes_from_hhmm(str(data["end_time"]))
        if end > start:
            windows.append((start, end))
    return _merge_intervals(windows)


def open_windows_for_date(
    weekly_hours: Sequence[WeeklyHoursRow],
    date_str: str,
    *,
    service_hours: Optional[Sequence[WeeklyHoursRow]] = None,
) -> List[Dict[str, str]]:
    """
    Build open windows for a clinic-local date from resource weekly_hours,
    optionally narrowed by service_hours.
    """
    day = date.fromisoformat(date_str).weekday()
    windows = _windows_for_weekday(weekly_hours, day)
    if service_hours is not None:
        narrower = _windows_for_weekday(service_hours, day)
        windows = _intersect_interval_lists(windows, narrower)
    return [
        {"start_time": hhmm_from_minutes(s), "end_time": hhmm_from_minutes(e)}
        for s, e in windows
    ]


def _blocking_busy_minutes(
    busy_intervals: Iterable[Mapping[str, Any]],
) -> List[Interval]:
    """Authoritative busy only; ignore cancelled / free / visibility_only rows."""
    blocking: List[Interval] = []
    for event in busy_intervals:
        if event.get("is_cancelled") is True:
            continue
        if event.get("visibility_only") is True:
            continue
        if event.get("authoritative") is False:
            continue
        if str(event.get("show_as") or "busy").lower() == "free":
            continue
        start = minutes_from_hhmm(str(event["start_time"]))
        end = minutes_from_hhmm(str(event["end_time"]))
        if end > start:
            blocking.append((start, end))
    return _merge_intervals(blocking)


def subtract_busy_from_windows(
    open_windows: Sequence[Mapping[str, str]],
    busy_intervals: Iterable[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    """Subtract busy intervals from open windows → free intervals (half-open)."""
    opens = [
        (minutes_from_hhmm(w["start_time"]), minutes_from_hhmm(w["end_time"]))
        for w in open_windows
    ]
    opens = _merge_intervals(opens)
    busy = _blocking_busy_minutes(busy_intervals)
    free: List[Interval] = []
    for win_start, win_end in opens:
        cursor = win_start
        for busy_start, busy_end in busy:
            if busy_end <= cursor or busy_start >= win_end:
                continue
            if busy_start > cursor:
                free.append((cursor, min(busy_start, win_end)))
            cursor = max(cursor, min(busy_end, win_end))
            if cursor >= win_end:
                break
        if cursor < win_end:
            free.append((cursor, win_end))
    return [
        {"start_time": hhmm_from_minutes(s), "end_time": hhmm_from_minutes(e)}
        for s, e in _merge_intervals(free)
    ]


def free_intervals_for_resource(
    weekly_hours: Sequence[WeeklyHoursRow],
    busy_intervals: Iterable[Mapping[str, Any]],
    date_str: str,
    *,
    service_hours: Optional[Sequence[WeeklyHoursRow]] = None,
) -> List[Dict[str, str]]:
    """
    Free intervals = resource weekly hours for date − that resource's busy.

    Busy from other resources must not be passed in — Discovery busy on the
    practitioner resource does not affect Salt room free time.
    """
    open_windows = open_windows_for_date(
        weekly_hours, date_str, service_hours=service_hours
    )
    return subtract_busy_from_windows(open_windows, busy_intervals)


def occupied_interval_for_session_start(
    session_start: str,
    *,
    prep_minutes: int,
    session_minutes: int,
    recovery_minutes: int,
) -> Dict[str, str]:
    """Return occupied [start, end) wall times for a customer session start."""
    total = occupied_minutes(prep_minutes, session_minutes, recovery_minutes)
    start_m = minutes_from_hhmm(session_start) - prep_minutes
    end_m = minutes_from_hhmm(session_start) + session_minutes + recovery_minutes
    if start_m < 0:
        raise ValueError("occupied start before midnight")
    if end_m - start_m != total:
        # Defensive: occupied_minutes already validated inputs.
        raise ValueError("occupied length mismatch")
    return {
        "start_time": hhmm_from_minutes(start_m),
        "end_time": hhmm_from_minutes(end_m),
    }


def _occupied_fits_free(
    occupied_start: int,
    occupied_end: int,
    free: Sequence[Interval],
) -> bool:
    for free_start, free_end in free:
        if occupied_start >= free_start and occupied_end <= free_end:
            return True
    return False


def candidate_session_starts(
    free_intervals: Sequence[Mapping[str, str]],
    *,
    prep_minutes: int,
    session_minutes: int,
    recovery_minutes: int,
    start_increment_minutes: int = 60,
    last_start_time: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    Walk the service/resource grid over free intervals; emit customer session
    {start_time, end_time} where the full occupied span fits in free time.
    """
    if start_increment_minutes <= 0:
        raise ValueError("start_increment_minutes must be positive")
    if session_minutes <= 0:
        raise ValueError("session_minutes must be positive")

    free = [
        (minutes_from_hhmm(w["start_time"]), minutes_from_hhmm(w["end_time"]))
        for w in free_intervals
    ]
    free = _merge_intervals(free)
    last_start_m = (
        minutes_from_hhmm(last_start_time) if last_start_time is not None else None
    )

    slots: List[Dict[str, str]] = []
    seen: set[int] = set()
    for free_start, free_end in free:
        # Earliest session start whose prep still lands inside this free interval.
        first_session = free_start + prep_minutes
        # Align up to grid (grid origin midnight).
        if first_session % start_increment_minutes != 0:
            first_session += start_increment_minutes - (
                first_session % start_increment_minutes
            )
        t = first_session
        while True:
            occupied_end = t + session_minutes + recovery_minutes
            occupied_start = t - prep_minutes
            if occupied_start < free_start or occupied_end > free_end:
                if occupied_start >= free_end:
                    break
                t += start_increment_minutes
                continue
            if last_start_m is not None and t > last_start_m:
                break
            if t not in seen and _occupied_fits_free(occupied_start, occupied_end, free):
                seen.add(t)
                slots.append(
                    {
                        "start_time": hhmm_from_minutes(t),
                        "end_time": hhmm_from_minutes(t + session_minutes),
                    }
                )
            t += start_increment_minutes
            if t - prep_minutes >= free_end:
                break

    return sorted(slots, key=lambda s: s["start_time"])


def service_forbids_weekday(
    date_str: str,
    *,
    flags: Optional[Mapping[str, Any]] = None,
    forbid_weekdays: Optional[Iterable[int]] = None,
) -> bool:
    """True when the service must not offer slots on this clinic-local weekday."""
    day = date.fromisoformat(date_str).weekday()
    banned = set(forbid_weekdays or ())
    if flags and flags.get("no_mondays"):
        banned.add(0)
    return day in banned


def session_slots_for_resource(
    *,
    date_str: str,
    weekly_hours: Sequence[WeeklyHoursRow],
    busy_intervals: Iterable[Mapping[str, Any]],
    prep_minutes: int = 0,
    session_minutes: int,
    recovery_minutes: int = 0,
    start_increment_minutes: int = 60,
    last_start_time: Optional[str] = None,
    service_hours: Optional[Sequence[WeeklyHoursRow]] = None,
    flags: Optional[Mapping[str, Any]] = None,
    forbid_weekdays: Optional[Iterable[int]] = None,
) -> List[Dict[str, str]]:
    """
    Full per-resource candidate list for one service on one date.

    Pass only busy_intervals for the required resource. Practitioner Discovery
    busy must not be mixed into Salt room busy (and vice versa).
    """
    if service_forbids_weekday(
        date_str, flags=flags, forbid_weekdays=forbid_weekdays
    ):
        return []

    free = free_intervals_for_resource(
        weekly_hours,
        busy_intervals,
        date_str,
        service_hours=service_hours,
    )
    return candidate_session_starts(
        free,
        prep_minutes=prep_minutes,
        session_minutes=session_minutes,
        recovery_minutes=recovery_minutes,
        start_increment_minutes=start_increment_minutes,
        last_start_time=last_start_time,
    )


def slots_for_open_dates_preview(
    *,
    date_str: str,
    resource: Mapping[str, Any],
    busy_intervals: Iterable[Mapping[str, Any]],
    prep_minutes: int = 0,
    session_minutes: int,
    recovery_minutes: int = 0,
    flags: Optional[Mapping[str, Any]] = None,
    service_hours: Optional[Sequence[WeeklyHoursRow]] = None,
) -> List[Dict[str, str]]:
    """
    Thin facade used by multi_resource_booking when the feature flag is on.

    Safe when resource fields are missing (empty list). Legacy booking paths
    must not call this while settings.multi_resource_scheduling is False.
    """
    weekly = resource.get("weekly_hours") or []
    if not weekly:
        return []
    grid = resource.get("slot_grid") or {}
    if hasattr(grid, "model_dump"):
        grid = grid.model_dump()
    increment = int(grid.get("start_increment_minutes") or 60) if grid else 60
    last_start = resource.get("last_start_time")
    return session_slots_for_resource(
        date_str=date_str,
        weekly_hours=weekly,
        busy_intervals=busy_intervals,
        prep_minutes=prep_minutes,
        session_minutes=session_minutes,
        recovery_minutes=recovery_minutes,
        start_increment_minutes=increment,
        last_start_time=str(last_start) if last_start else None,
        service_hours=service_hours,
        flags=flags,
    )
