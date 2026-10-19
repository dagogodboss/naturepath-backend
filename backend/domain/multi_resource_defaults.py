"""
Locked Phase 0 defaults for multi-resource Outlook + Salt scheduling.

Code hooks only — OAuth for Clients@thenaturalpathla.com is an ops task; see
docs/plans/phase-0-outlook-categories-setup.md.
"""

from __future__ import annotations

from typing import Any, List, Sequence

from domain.entities.models import OutlookCategoryMap

# LOCKED Message 3 — Salt busy authority (not Nichole's calendar for Salt).
SALT_OUTLOOK_MAILBOX = "Clients@thenaturalpathla.com"

# Ops checklist exact display names (phase-0-outlook-categories-setup.md).
CATEGORY_DISCOVERY = "Discovery"
CATEGORY_CONSULTATION = "Consultation"
CATEGORY_SALT_SESSION = "Salt Session"
CATEGORY_BUSINESS_CLOSURE = "Business Closure"
# Legacy alias still seen in some calendars — map to Salt room alongside Salt Session.
CATEGORY_SALT_LEGACY = "Salt"


def build_nichole_authoritative_category_maps(
    nichole_resource_id: str,
    salt_resource_id: str,
) -> List[OutlookCategoryMap]:
    """
    Category maps for Nichole's authoritative mailbox connection.

    Prefer shared Clients@ for Salt visibility. If Salt Session / Salt copies
    appear on Nichole's calendar, map them as visibility_only so they never
    consume practitioner capacity or double-count the room (#9 B3).
    """
    return [
        OutlookCategoryMap(
            category_name=CATEGORY_DISCOVERY,
            resource_ids=[nichole_resource_id],
        ),
        OutlookCategoryMap(
            category_name=CATEGORY_CONSULTATION,
            resource_ids=[nichole_resource_id],
        ),
        OutlookCategoryMap(
            category_name=CATEGORY_BUSINESS_CLOSURE,
            resource_ids=[nichole_resource_id, salt_resource_id],
            blocks_all_authoritative=True,
        ),
        OutlookCategoryMap(
            category_name=CATEGORY_SALT_SESSION,
            resource_ids=[salt_resource_id],
            visibility_only=True,
        ),
        OutlookCategoryMap(
            category_name=CATEGORY_SALT_LEGACY,
            resource_ids=[salt_resource_id],
            visibility_only=True,
        ),
    ]


def nichole_visibility_copy_category_names() -> List[str]:
    """Explicit Salt visibility-copy markers for Nichole's mailbox."""
    return [CATEGORY_SALT_SESSION, CATEGORY_SALT_LEGACY]


def build_clients_salt_authoritative_category_maps(
    salt_resource_id: str,
    nichole_resource_id: str,
) -> List[OutlookCategoryMap]:
    """Category maps for Clients@ authoritative Salt mailbox."""
    return [
        OutlookCategoryMap(
            category_name=CATEGORY_SALT_SESSION,
            resource_ids=[salt_resource_id],
        ),
        OutlookCategoryMap(
            category_name=CATEGORY_SALT_LEGACY,
            resource_ids=[salt_resource_id],
        ),
        OutlookCategoryMap(
            category_name=CATEGORY_BUSINESS_CLOSURE,
            resource_ids=[nichole_resource_id, salt_resource_id],
            blocks_all_authoritative=True,
        ),
    ]


def outlook_connection_multi_resource_patch(
    *,
    mailbox_email: str,
    authoritative_for_resource_ids: Sequence[str],
    category_maps: Sequence[OutlookCategoryMap],
    visibility_only: bool = False,
    visibility_copy_category_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    """
    Fields to merge onto an outlook_calendar_connections document when enabling
    multi-resource sync (Phase 2). Does not perform OAuth or writes.
    """
    patch: dict[str, Any] = {
        "mailbox_email": mailbox_email,
        "authoritative_for_resource_ids": list(authoritative_for_resource_ids),
        "category_maps": [m.model_dump() for m in category_maps],
        "visibility_only": visibility_only,
    }
    if visibility_copy_category_names is not None:
        patch["visibility_copy_category_names"] = list(visibility_copy_category_names)
    return patch


def build_locked_outlook_connection_templates(
    nichole_resource_id: str,
    salt_resource_id: str,
    *,
    nichole_mailbox_email: str | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Two-connection template: Nichole practitioner auth + Clients@ Salt auth.

    Prefer staff viewing the shared Clients@ calendar alongside Nichole (no
    occupancy from copies). Nichole template still lists Salt categories as
    visibility-only markers when copies exist inside her calendar (#9 B3).
    """
    nichole_email = nichole_mailbox_email or "(link via practitioner OAuth)"
    return {
        "nichole_authoritative": outlook_connection_multi_resource_patch(
            mailbox_email=nichole_email,
            authoritative_for_resource_ids=[nichole_resource_id],
            category_maps=build_nichole_authoritative_category_maps(
                nichole_resource_id, salt_resource_id
            ),
            visibility_copy_category_names=nichole_visibility_copy_category_names(),
        ),
        "clients_salt_authoritative": outlook_connection_multi_resource_patch(
            mailbox_email=SALT_OUTLOOK_MAILBOX,
            authoritative_for_resource_ids=[salt_resource_id],
            category_maps=build_clients_salt_authoritative_category_maps(
                salt_resource_id, nichole_resource_id
            ),
        ),
    }
