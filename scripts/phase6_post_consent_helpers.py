"""Pure helpers for post–Entra-consent cutover (unit-testable, no I/O)."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


DEFAULT_MAILBOXES: tuple[str, ...] = (
    "Clients@thenaturalpathla.com",
    "nmoore@thenaturalpathla.com",
)

STAGING_CONNECTION_IDS: dict[str, str] = {
    "clients": "9fba4c5f-38e7-4a69-888c-3f84627ed3ea",
    "nichole": "0ae88711-4e79-42b4-831f-141705d6ca9c",
}

PROD_CONNECTION_IDS: dict[str, str] = {
    "clients": "a5d43af5-0f20-4871-8d79-5af254b1e936",
    "nichole": "0ae88711-4e79-42b4-831f-141705d6ca9c",
}

REQUIRED_STAGING_RUN_ENV: dict[str, str] = {
    "MULTI_RESOURCE_SCHEDULING": "true",
    "OUTLOOK_APP_ONLY_SYNC_ENABLED": "true",
}

EXIT_CONSENT_BLOCKER = 10
EXIT_STAGING_FAILED = 1
EXIT_PROD_GATE = 11


@dataclass(frozen=True)
class ProbeVerdict:
    ok: bool
    code: str
    message: str
    mailboxes: tuple[dict[str, Any], ...]


def _is_access_denied(text: str) -> bool:
    lowered = text.lower()
    return "403" in lowered or "erroraccessdenied" in lowered or "access denied" in lowered


def evaluate_mailbox_probes(entries: Sequence[Mapping[str, Any]]) -> ProbeVerdict:
    """Return ok when every mailbox probe succeeded with status ok."""
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        row = dict(entry)
        normalized.append(row)
        status = str(row.get("status") or "")
        if status == "ok":
            continue
        err = str(row.get("error") or "")
        mailbox = row.get("mailbox") or row.get("upn") or "unknown"
        if _is_access_denied(err):
            return ProbeVerdict(
                ok=False,
                code="entra_admin_consent_required",
                message=(
                    f"Graph app-only calendar access still denied for {mailbox}. "
                    "Complete Entra admin consent for Calendars.Read (application), "
                    "then re-run this script."
                ),
                mailboxes=tuple(normalized),
            )
        if not row.get("token_acquired", True):
            return ProbeVerdict(
                ok=False,
                code="microsoft_token_failed",
                message=f"Could not acquire client_credentials token (mailbox={mailbox}).",
                mailboxes=tuple(normalized),
            )
        return ProbeVerdict(
            ok=False,
            code="graph_probe_failed",
            message=f"Mailbox probe failed for {mailbox}: {err[:240]}",
            mailboxes=tuple(normalized),
        )
    return ProbeVerdict(
        ok=True,
        code="ok",
        message="App-only Graph calendar probes succeeded for all mailboxes.",
        mailboxes=tuple(normalized),
    )


def staging_env_gaps(run_env: Mapping[str, str]) -> list[str]:
    """List missing or wrong Cloud Run env vars for staging cutover."""
    gaps: list[str] = []
    for key, expected in REQUIRED_STAGING_RUN_ENV.items():
        actual = str(run_env.get(key) or "").strip().lower()
        if actual != expected.lower():
            gaps.append(f"{key}={actual or '(unset)'} (need {expected})")
    return gaps


def validate_prod_gate(*, prod: bool, dry_run: bool, i_understand_prod: bool) -> str | None:
    if not prod:
        return None
    if dry_run:
        return "Refusing --prod with --dry-run (remove one flag)."
    if not i_understand_prod:
        return "Prod cutover requires --i-understand-prod (staging prove must pass first)."
    return None


def qa_artifact_name(*, phase: str, stamp: str | None = None) -> str:
    safe_phase = re.sub(r"[^a-z0-9-]+", "-", phase.lower()).strip("-")
    day = stamp or datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"post-consent-cutover-{safe_phase}-{day}.json"


def decode_jwt_roles(access_token: str) -> list[str]:
    """Best-effort parse of JWT roles claim (no signature verify — diagnostics only)."""
    try:
        parts = access_token.split(".")
        if len(parts) < 2:
            return []
        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        raw = base64.urlsafe_b64decode(payload + padding)
        data = json.loads(raw.decode("utf-8"))
        roles = data.get("roles") or []
        return [str(r) for r in roles]
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return []


def busy_intervals_assertion(
    counts: Mapping[str, int],
    *,
    allow_empty: bool,
) -> tuple[bool, str]:
    total = sum(int(v) for v in counts.values())
    if total > 0:
        return True, f"resource_busy_intervals total={total}"
    if allow_empty:
        return True, (
            "resource_busy_intervals empty — calendars may have no events in window; "
            "Discovery≠Salt prove may still fail without real busy."
        )
    return False, "resource_busy_intervals empty after sync (expected Outlook busy data)."


# Sources that must never satisfy a "real Outlook busy" gate.
SYNTHETIC_BUSY_SOURCES: frozenset[str] = frozenset(
    {
        "staging_prove_synthetic",
        "synthetic_prove",
        "prove_synthetic",
    }
)


def is_synthetic_busy_source(source: Any) -> bool:
    text = str(source or "").strip().lower()
    if not text:
        return False
    if text in SYNTHETIC_BUSY_SOURCES:
        return True
    return "synthetic" in text


def real_outlook_busy_assertion(
    intervals: Sequence[Mapping[str, Any]],
    *,
    require_non_empty: bool = True,
) -> tuple[bool, str]:
    """
    Pass only when at least one interval looks like real Outlook/sync busy.

    Rejects empty sets (unless require_non_empty=False) and any set that is
    exclusively synthetic prove injects.
    """
    rows = list(intervals)
    if not rows:
        if require_non_empty:
            return False, "no busy intervals on prove date (need real Outlook busy)"
        return True, "no busy intervals (allowed)"

    real_rows = [r for r in rows if not is_synthetic_busy_source(r.get("source"))]
    synthetic_rows = [r for r in rows if is_synthetic_busy_source(r.get("source"))]
    if not real_rows:
        return False, (
            f"only synthetic busy present ({len(synthetic_rows)}); "
            "refusing real-Outlook prove gate"
        )
    return True, f"real_busy_count={len(real_rows)} synthetic_busy_count={len(synthetic_rows)}"


def prod_cutover_steps() -> tuple[str, ...]:
    """Documented order for run_prod_phase (flag enable is always last)."""
    return (
        "validate",
        "patch_auth_mode",
        "sync",
        "prove_real_busy",
        "enable_flag",
    )
