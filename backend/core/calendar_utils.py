"""
Calendar helpers: iCal (.ics) and deep links for Google Calendar & Microsoft Outlook on the web.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any, Dict
from urllib.parse import quote, urlencode
from uuid import uuid4


def _escape_ics_text(value: str) -> str:
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\n")
        .replace("\n", "\\n")
    )


def _ics_datetime_local(date_str: str, time_str: str) -> str:
    t = (time_str or "00:00").strip()
    if len(t) == 5:
        t += ":00"
    parts = t.split(":")
    hh, mm = parts[0], parts[1] if len(parts) > 1 else "00"
    ss = parts[2] if len(parts) > 2 else "00"
    ds = date_str.replace("-", "")
    return f"{ds}T{hh.zfill(2)}{mm.zfill(2)}{ss.zfill(2)}"


def build_booking_ical(booking: Dict[str, Any]) -> str:
    """Build RFC 5545 .ics content for a booking dict (same shape as get_booking_by_id)."""
    slot = booking.get("slot") or {}
    service = booking.get("service") or {}
    practitioner = booking.get("practitioner") or {}
    cust = booking.get("customer") or {}
    date_s = slot.get("date") or ""
    start = slot.get("start_time") or "09:00"
    end = slot.get("end_time") or start
    summary = service.get("name") or "Appointment"
    pname = ""
    if practitioner:
        pu = practitioner.get("user") or {}
        fn = practitioner.get("first_name") or pu.get("first_name", "")
        ln = practitioner.get("last_name") or pu.get("last_name", "")
        pname = f"{fn} {ln}".strip()
    desc_bits = [
        f"Booking ID: {booking.get('booking_id', '')}",
        f"Client: {cust.get('first_name', '')} {cust.get('last_name', '')}".strip(),
    ]
    if pname:
        desc_bits.append(f"Practitioner: {pname}")
    description = _escape_ics_text(" | ".join(b for b in desc_bits if b))
    summary_esc = _escape_ics_text(summary)
    uid = f"{booking.get('booking_id', str(uuid4()))}@natural-path-spa"
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dtstart = _ics_datetime_local(date_s, start)
    dtend = _ics_datetime_local(date_s, end)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Natural Path Spa//Booking//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:{summary_esc}",
        f"DESCRIPTION:{description}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def ical_to_base64(ics: str) -> str:
    return base64.standard_b64encode(ics.encode("utf-8")).decode("ascii")


def _parse_local_start_end(date_str: str, start_time: str, end_time: str) -> tuple[str, str]:
    """Return (google_dates_param, iso_start, iso_end) for link builders."""
    ds = date_str.replace("-", "")
    st = (start_time or "09:00").strip()
    if len(st) == 5:
        st += ":00"
    et = (end_time or st).strip()
    if len(et) == 5:
        et += ":00"
    sp = st.split(":")
    ep = et.split(":")
    g_start = f"{ds}T{sp[0].zfill(2)}{sp[1].zfill(2)}{sp[2].zfill(2) if len(sp) > 2 else '00'}"
    g_end = f"{ds}T{ep[0].zfill(2)}{ep[1].zfill(2)}{ep[2].zfill(2) if len(ep) > 2 else '00'}"
    iso_start = f"{date_str}T{st}"
    iso_end = f"{date_str}T{et}"
    return f"{g_start}/{g_end}", iso_start, iso_end


def google_calendar_template_url(
    title: str,
    date_str: str,
    start_time: str,
    end_time: str,
    details: str = "",
    location: str = "",
) -> str:
    dates, _, _ = _parse_local_start_end(date_str, start_time, end_time)
    q = urlencode(
        {
            "action": "TEMPLATE",
            "text": title,
            "dates": dates,
            "details": details,
            "location": location,
        },
        quote_via=quote,
    )
    return f"https://calendar.google.com/calendar/render?{q}"


def microsoft_calendar_template_url(
    title: str,
    date_str: str,
    start_time: str,
    end_time: str,
    body: str = "",
    location: str = "",
) -> str:
    _, iso_start, iso_end = _parse_local_start_end(date_str, start_time, end_time)
    q = urlencode(
        {
            "path": "/calendar/action/compose",
            "rru": "addevent",
            "subject": title,
            "startdt": iso_start,
            "enddt": iso_end,
            "body": body,
            "location": location,
        },
        quote_via=quote,
    )
    return f"https://outlook.live.com/calendar/0/deeplink/compose?{q}"


def outlook_office_calendar_template_url(
    title: str,
    date_str: str,
    start_time: str,
    end_time: str,
    body: str = "",
    location: str = "",
) -> str:
    """Alternative for Microsoft 365 / work accounts (same query pattern)."""
    _, iso_start, iso_end = _parse_local_start_end(date_str, start_time, end_time)
    q = urlencode(
        {
            "path": "/calendar/action/compose",
            "rru": "addevent",
            "subject": title,
            "startdt": iso_start,
            "enddt": iso_end,
            "body": body,
            "location": location,
        },
        quote_via=quote,
    )
    return f"https://outlook.office.com/calendar/0/deeplink/compose?{q}"
