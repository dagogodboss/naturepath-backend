"""
Phase 2 scaffold: Outlook Graph category → resource busy intervals.

Pure classification + dual-write helpers. Active only when
settings.multi_resource_scheduling is True (see outlook_sync).
"""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from application.multi_resource_conflicts import enqueue_sync_conflicts_for_busy_intervals
from domain.entities.models import (
    BusyIntervalSource,
    ResourceBusyInterval,
    ReviewQueueItem,
    ReviewQueueItemStatus,
    ReviewQueueItemType,
)
from infrastructure.external.microsoft_graph import event_to_busy_intervals


class MultiResourceSyncConfigError(Exception):
    """Missing maps/resources — refuse to wipe resource busy (fail closed)."""

    def __init__(self, message: str):
        super().__init__(message)


def normalize_category_name(name: str) -> str:
    """Casefold + trim for Outlook category display name matching."""
    return str(name or "").strip().casefold()


def _next_sync_generation() -> int:
    """Monotonic-ish generation id for fail-safe busy snapshot replace."""
    return time.time_ns()


def _connection_field(connection: Mapping[str, Any], key: str, default: Any = None) -> Any:
    if hasattr(connection, key):
        value = getattr(connection, key)
        if value is not None:
            return value
    return connection.get(key, default) if hasattr(connection, "get") else default


def category_map_index(
    category_maps: Sequence[Mapping[str, Any]],
) -> Dict[str, List[str]]:
    """category_name (normalized) → resource_ids (union if duplicates)."""
    index: Dict[str, List[str]] = {}
    for entry in category_maps or []:
        if hasattr(entry, "model_dump"):
            entry = entry.model_dump()
        name = normalize_category_name(str(entry.get("category_name") or ""))
        if not name:
            continue
        ids = [str(r) for r in (entry.get("resource_ids") or []) if r]
        if name not in index:
            index[name] = []
        for rid in ids:
            if rid not in index[name]:
                index[name].append(rid)
    return index


def _category_map_entries(
    category_maps: Sequence[Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """normalized category → first map entry (visibility_only + resource_ids)."""
    out: Dict[str, Dict[str, Any]] = {}
    for entry in category_maps or []:
        if hasattr(entry, "model_dump"):
            entry = entry.model_dump()
        name = normalize_category_name(str(entry.get("category_name") or ""))
        if not name or name in out:
            continue
        out[name] = entry
    return out


@dataclass(frozen=True)
class EventResourceMapping:
    """Result of mapping one Graph event's categories to resource ids."""

    resource_ids: Tuple[str, ...] = ()
    matched_category_names: Tuple[str, ...] = ()
    review_type: Optional[ReviewQueueItemType] = None
    review_message: Optional[str] = None
    occupy: bool = False
    authoritative: bool = True


def _visibility_copy_name_set(
    visibility_copy_category_names: Optional[Sequence[str]],
) -> set[str]:
    return {
        normalize_category_name(str(n))
        for n in (visibility_copy_category_names or [])
        if str(n).strip()
    }


def map_event_categories_to_resource_ids(
    event: Mapping[str, Any],
    *,
    category_maps: Sequence[Mapping[str, Any]],
    authoritative_for_resource_ids: Sequence[str],
    visibility_only: bool = False,
    visibility_copy_category_names: Optional[Sequence[str]] = None,
) -> EventResourceMapping:
    """
    Pure helper: Graph event categories → resource_ids (+ optional review).

    Rules (Phase 2 / Phase 0 Q4 + #9 B3):
    - connection visibility_only → no authoritative occupy
    - free / cancelled → no occupy
    - explicit visibility-copy category names / map.visibility_only → no occupy
      (Salt copies on Nichole; never infer from title/color)
    - mapped occupy categories → union of mapped resource_ids
    - mapped only to non-authoritative resources → visibility copy (no occupy)
    - unmapped busy on authoritative mailbox → authoritative_for_resource_ids
      + unmapped_category review (mystery busy stays blocked)
    """
    if visibility_only:
        return EventResourceMapping(occupy=False, authoritative=False)

    show_as = str(event.get("showAs") or event.get("show_as") or "busy").lower()
    is_cancelled = bool(event.get("isCancelled", event.get("is_cancelled", False)))
    if is_cancelled or show_as == "free":
        return EventResourceMapping(occupy=False, authoritative=True)

    raw_categories = event.get("categories") or []
    if not isinstance(raw_categories, (list, tuple)):
        raw_categories = []

    copy_names = _visibility_copy_name_set(visibility_copy_category_names)
    entries = _category_map_entries(category_maps)
    auth_ids = [str(r) for r in (authoritative_for_resource_ids or []) if r]
    auth_set = set(auth_ids)

    matched_names: List[str] = []
    resource_ids: List[str] = []
    saw_visibility_copy = False

    for cat in raw_categories:
        key = normalize_category_name(str(cat))
        if not key:
            continue
        label = str(cat).strip()
        entry = entries.get(key)
        explicit_copy = key in copy_names or bool(
            entry and entry.get("visibility_only")
        )
        if explicit_copy:
            saw_visibility_copy = True
            if label and label not in matched_names:
                matched_names.append(label)
            continue
        if not entry:
            continue
        if label and label not in matched_names:
            matched_names.append(label)
        for rid in entry.get("resource_ids") or []:
            rid_s = str(rid)
            if rid_s and rid_s not in resource_ids:
                resource_ids.append(rid_s)

    if resource_ids:
        # Foreign-only maps on this mailbox are visibility copies (Clients@ owns Salt).
        if auth_set and not any(rid in auth_set for rid in resource_ids):
            return EventResourceMapping(
                resource_ids=(),
                matched_category_names=tuple(matched_names),
                occupy=False,
                authoritative=False,
            )
        return EventResourceMapping(
            resource_ids=tuple(resource_ids),
            matched_category_names=tuple(matched_names),
            occupy=True,
            authoritative=True,
        )

    if saw_visibility_copy:
        return EventResourceMapping(
            resource_ids=(),
            matched_category_names=tuple(matched_names),
            occupy=False,
            authoritative=False,
        )

    # Unmapped busy on authoritative mailbox → default auth resources + review.
    if not auth_ids:
        return EventResourceMapping(occupy=False, authoritative=True)

    unmapped_label = ", ".join(str(c).strip() for c in raw_categories if str(c).strip())
    return EventResourceMapping(
        resource_ids=tuple(auth_ids),
        matched_category_names=(),
        review_type=ReviewQueueItemType.UNMAPPED_CATEGORY,
        review_message=(
            "Unclassified busy on authoritative mailbox"
            + (f" (categories: {unmapped_label})" if unmapped_label else "")
            + "; blocked default authoritative resource(s)."
        ),
        occupy=True,
        authoritative=True,
    )


@dataclass
class BuiltBusyDocuments:
    intervals: List[Dict[str, Any]] = field(default_factory=list)
    review_items: List[Dict[str, Any]] = field(default_factory=list)


def build_resource_busy_documents(
    events: Iterable[Mapping[str, Any]],
    connection: Mapping[str, Any],
    *,
    clinic_timezone: str,
    synced_at: Optional[datetime] = None,
) -> BuiltBusyDocuments:
    """
    Build ResourceBusyInterval + ReviewQueueItem docs from Graph events.

    Pure (no DB). One interval row per (resource_id × day segment).
    """
    connection_id = str(_connection_field(connection, "connection_id") or "")
    visibility_only = bool(_connection_field(connection, "visibility_only", False))
    category_maps = _connection_field(connection, "category_maps") or []
    auth_ids = _connection_field(connection, "authoritative_for_resource_ids") or []
    visibility_copy_names = (
        _connection_field(connection, "visibility_copy_category_names") or []
    )
    when = synced_at or datetime.now(timezone.utc)

    out = BuiltBusyDocuments()
    for event in events:
        mapping = map_event_categories_to_resource_ids(
            event,
            category_maps=category_maps,
            authoritative_for_resource_ids=auth_ids,
            visibility_only=visibility_only,
            visibility_copy_category_names=visibility_copy_names,
        )
        if not mapping.occupy or not mapping.resource_ids:
            continue

        day_segments = event_to_busy_intervals(dict(event), clinic_timezone)
        primary_category = (
            mapping.matched_category_names[0]
            if mapping.matched_category_names
            else None
        )
        for segment in day_segments:
            for resource_id in mapping.resource_ids:
                interval = ResourceBusyInterval(
                    resource_id=resource_id,
                    date=segment["date"],
                    start_time=segment["start_time"],
                    end_time=segment["end_time"],
                    starts_at=_as_datetime(segment.get("starts_at")),
                    ends_at=_as_datetime(segment.get("ends_at")),
                    source=BusyIntervalSource.OUTLOOK,
                    authoritative=mapping.authoritative,
                    connection_id=connection_id or None,
                    event_id=str(segment.get("event_id") or event.get("id") or ""),
                    category_name=primary_category,
                    show_as=str(segment.get("show_as") or "busy"),
                    is_cancelled=bool(segment.get("is_cancelled", False)),
                    synced_at=when,
                )
                out.intervals.append(_model_to_mongo(interval))

        if mapping.review_type and mapping.review_message:
            item = ReviewQueueItem(
                type=mapping.review_type,
                status=ReviewQueueItemStatus.OPEN,
                resource_id=mapping.resource_ids[0] if mapping.resource_ids else None,
                connection_id=connection_id or None,
                event_id=str(event.get("id") or "") or None,
                category_name=primary_category,
                message=mapping.review_message,
                payload={
                    "categories": list(event.get("categories") or []),
                    "matched_category_names": list(mapping.matched_category_names),
                    "resource_ids": list(mapping.resource_ids),
                    "subject": event.get("subject"),
                },
                created_at=when,
            )
            out.review_items.append(_model_to_mongo(item))

    return out


def _as_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _model_to_mongo(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return dict(model)


def validate_multi_resource_sync_ready(
    connection: Mapping[str, Any],
    *,
    known_resource_ids: Optional[Iterable[str]] = None,
) -> None:
    """
    Fail closed if flag-on sync cannot classify safely.

    Raises MultiResourceSyncConfigError when maps/auth resources are missing
    so callers must not wipe resource_busy_intervals.
    """
    visibility_only = bool(_connection_field(connection, "visibility_only", False))
    if visibility_only:
        return

    category_maps = list(_connection_field(connection, "category_maps") or [])
    auth_ids = [
        str(r)
        for r in (_connection_field(connection, "authoritative_for_resource_ids") or [])
        if r
    ]
    if not category_maps:
        raise MultiResourceSyncConfigError(
            "Multi-resource Outlook sync requires category_maps on the connection. "
            "Refusing to replace resource busy intervals."
        )
    if not auth_ids:
        raise MultiResourceSyncConfigError(
            "Multi-resource Outlook sync requires authoritative_for_resource_ids "
            "on the connection. Refusing to replace resource busy intervals."
        )

    if known_resource_ids is None:
        return

    known = {str(r) for r in known_resource_ids}
    needed: List[str] = list(auth_ids)
    for entry in category_maps:
        if hasattr(entry, "model_dump"):
            entry = entry.model_dump()
        # Visibility-only maps may reference foreign resources for labeling only.
        if entry.get("visibility_only"):
            continue
        for rid in entry.get("resource_ids") or []:
            if rid and str(rid) not in needed:
                needed.append(str(rid))
    missing = [r for r in needed if r not in known]
    if missing:
        raise MultiResourceSyncConfigError(
            "Multi-resource Outlook sync is missing resources: "
            + ", ".join(missing)
            + ". Refusing to replace resource busy intervals."
        )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _claim_busy_sync_generation(
    db: Any,
    connection_id: str,
    generation: int,
) -> bool:
    """
    CAS: set active_busy_generation when missing or older than generation.

    Returns False when a newer generation already won (stale sync must not
    delete the winner's rows).
    """
    connections = getattr(db, "outlook_calendar_connections", None)
    if connections is None:
        return True
    update_one = getattr(connections, "update_one", None)
    if update_one is None:
        return True

    result = await _maybe_await(
        update_one(
            {
                "connection_id": connection_id,
                "$or": [
                    {"active_busy_generation": {"$exists": False}},
                    {"active_busy_generation": None},
                    {"active_busy_generation": {"$lt": generation}},
                ],
            },
            {
                "$set": {
                    "active_busy_generation": generation,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            },
        )
    )
    try:
        modified = int(getattr(result, "modified_count", 0) or 0)
    except (TypeError, ValueError):
        # Unit-test doubles without a real UpdateResult — allow replace.
        return True
    if modified:
        return True

    find_one = getattr(connections, "find_one", None)
    if find_one is None:
        return True
    doc = await _maybe_await(
        find_one({"connection_id": connection_id}, {"active_busy_generation": 1})
    )
    if not isinstance(doc, Mapping):
        # MagicMock / missing collection in unit tests — allow replace.
        return True
    active = doc.get("active_busy_generation")
    if active is None:
        return True
    try:
        return int(active) <= int(generation)
    except (TypeError, ValueError):
        return True


async def persist_resource_busy_from_events(
    db: Any,
    connection: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    *,
    clinic_timezone: str,
    synced_at: Optional[datetime] = None,
) -> Dict[str, int]:
    """
    Classify events and fail-safe replace outlook-sourced resource busy rows.

    Insert (or empty classify) before deleting prior generations so a crash
    never leaves an empty busy window. Concurrent older generations cannot
    overwrite a newer active_busy_generation.
    """
    connection_id = str(_connection_field(connection, "connection_id") or "")
    known_ids: Optional[List[str]] = None
    resources = getattr(db, "resources", None)
    if resources is not None:
        rows = await resources.find({}, {"_id": 0, "resource_id": 1}).to_list(length=500)
        known_ids = [str(r["resource_id"]) for r in rows if r.get("resource_id")]

    validate_multi_resource_sync_ready(connection, known_resource_ids=known_ids)

    built = build_resource_busy_documents(
        events,
        connection,
        clinic_timezone=clinic_timezone,
        synced_at=synced_at,
    )

    busy_col = getattr(db, "resource_busy_intervals", None)
    review_col = getattr(db, "review_queue", None)
    if busy_col is None:
        raise MultiResourceSyncConfigError(
            "resource_busy_intervals collection is unavailable. "
            "Refusing multi-resource Outlook sync write."
        )

    generation = _next_sync_generation()
    for row in built.intervals:
        row["sync_generation"] = generation
    for row in built.review_items:
        row["sync_generation"] = generation

    # 1) Insert new snapshot first (prior generation remains readable).
    if built.intervals:
        await busy_col.insert_many(built.intervals)

    # 2) Claim generation; losers discard their insert and keep the winner.
    won = await _claim_busy_sync_generation(db, connection_id, generation)
    if not won:
        await busy_col.delete_many(
            {
                "connection_id": connection_id,
                "source": BusyIntervalSource.OUTLOOK.value,
                "sync_generation": generation,
            }
        )
        return {
            "resource_interval_count": 0,
            "review_item_count": 0,
            "sync_conflict_review_count": 0,
            "skipped_stale_generation": True,
        }

    # 3) Remove superseded / legacy untagged outlook rows for this connection.
    await busy_col.delete_many(
        {
            "connection_id": connection_id,
            "source": BusyIntervalSource.OUTLOOK.value,
            "$or": [
                {"sync_generation": {"$ne": generation}},
                {"sync_generation": {"$exists": False}},
            ],
        }
    )

    if review_col is not None:
        if built.review_items:
            await review_col.insert_many(built.review_items)
        await review_col.delete_many(
            {
                "connection_id": connection_id,
                "status": ReviewQueueItemStatus.OPEN.value,
                "type": {
                    "$in": [
                        ReviewQueueItemType.UNMAPPED_CATEGORY.value,
                        ReviewQueueItemType.SYNC_CONFLICT.value,
                    ]
                },
                "$or": [
                    {"sync_generation": {"$ne": generation}},
                    {"sync_generation": {"$exists": False}},
                ],
            }
        )

    sync_conflict_review_count = await enqueue_sync_conflicts_for_busy_intervals(
        db,
        busy_intervals=built.intervals,
    )

    return {
        "resource_interval_count": len(built.intervals),
        "review_item_count": len(built.review_items),
        "sync_conflict_review_count": sync_conflict_review_count,
    }
