#!/usr/bin/env python3
"""
In-process proof of Discovery ≠ Salt (Phase 6 / P1–P2 core).

Runs against pure `multi_resource_slots` with synthetic busy intervals.
No Mongo, no Graph, no production, no booking_open_dates wiring.

Pass criteria (automated core of production checklist P1/P2):
  P1-core: Discovery occupied on Nichole at 15:00 CT blocks Discovery 15:00
  P2-core: Same wall clock — Salt room still offers 15:00 (customer 45 → 15:45)

Also checks T2 inverse (Salt busy ≠ Discovery blocked) and Monday Discovery
closed / Salt open (P4-core), matching Phase 3 unit cases T1–T3.

Salt window (LOCKED Q1/Q6): M–F 10:30–18:00, last start 17:00,
customer 45 + cleanup 15 = occupied 60. Outlook: Clients@.

Usage (from backend/ — the package root that contains scripts/ and backend/):
  PYTHONPATH=backend python -m scripts.prove_multi_resource_slots

Exit 0 on pass; non-zero on any invariant failure. Does not enable
MULTI_RESOURCE_SCHEDULING and does not touch booking paths.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Sequence

_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _THIS_DIR.parent / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from application.multi_resource_slots import (  # noqa: E402
    occupied_interval_for_session_start,
    session_slots_for_resource,
)
from core.config import MULTI_RESOURCE_SCHEDULING  # noqa: E402
from domain.entities.models import PractitionerAvailability  # noqa: E402

# Clinic-local wall clock (America/Chicago). 2026-10-20 = Tuesday; 2026-10-19 = Monday.
TUE = "2026-10-20"
MON = "2026-10-19"

NICHOLE_HOURS = [
    PractitionerAvailability(day_of_week=d, start_time="09:00", end_time="17:00")
    for d in range(1, 6)  # Tue–Sat resource hours; Discovery uses no_mondays
]
NICHOLE_HOURS_WITH_MON = [
    PractitionerAvailability(day_of_week=d, start_time="09:00", end_time="17:00")
    for d in range(0, 5)
]
# LOCKED Q6: Salt Mon–Fri 10:30–18:00
SALT_HOURS = [
    PractitionerAvailability(day_of_week=d, start_time="10:30", end_time="18:00")
    for d in range(5)
]

# LOCKED Q1: customer 45 + cleanup 15 = occupied 60
SALT_SESSION = 45
SALT_RECOVERY = 15
SALT_LAST_START = "17:00"


def _starts(slots: Sequence[dict]) -> List[str]:
    return [s["start_time"] for s in slots]


def _check(name: str, condition: bool, detail: str, failures: List[str]) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}: {detail}")
    if not condition:
        failures.append(f"{name}: {detail}")


def prove_discovery_neq_salt() -> List[str]:
    """
    Synthetic P1/P2: Nichole busy from Discovery occupied span at 15:00;
    Salt must still offer 15:00. Discovery must not.
    """
    failures: List[str] = []

    # Discovery: 30m session + 15m recovery → occupied 15:00–15:45 (prep 0).
    occupied = occupied_interval_for_session_start(
        "15:00", prep_minutes=0, session_minutes=30, recovery_minutes=15
    )
    nichole_busy = [
        {
            "resource_id": "res-nichole",
            "date": TUE,
            "start_time": occupied["start_time"],
            "end_time": occupied["end_time"],
            "show_as": "busy",
            "authoritative": True,
            "category_name": "Discovery",
            "source": "synthetic_prove",
        }
    ]

    discovery_slots = session_slots_for_resource(
        date_str=TUE,
        weekly_hours=NICHOLE_HOURS,
        busy_intervals=nichole_busy,
        prep_minutes=0,
        session_minutes=30,
        recovery_minutes=15,
        start_increment_minutes=60,
        flags={"no_mondays": True},
    )
    salt_slots = session_slots_for_resource(
        date_str=TUE,
        weekly_hours=SALT_HOURS,
        # Invariant: Discovery busy must not be passed for Salt.
        busy_intervals=[],
        prep_minutes=0,
        session_minutes=SALT_SESSION,
        recovery_minutes=SALT_RECOVERY,
        start_increment_minutes=60,
        last_start_time=SALT_LAST_START,
    )

    _check(
        "P1-core",
        "15:00" not in _starts(discovery_slots),
        "Discovery at 15:00 blocked on Nichole after synthetic Discovery busy",
        failures,
    )
    _check(
        "P2-core",
        {"start_time": "15:00", "end_time": "15:45"} in salt_slots,
        "Salt still offers 15:00–15:45 same wall clock (Discovery busy not applied)",
        failures,
    )
    return failures


def prove_salt_neq_discovery() -> List[str]:
    """T2 / P3-core inverse: Salt room busy must not remove Discovery 15:00."""
    failures: List[str] = []
    salt_busy = [
        {
            "resource_id": "res-salt",
            "date": TUE,
            "start_time": "15:00",
            "end_time": "16:00",
            "show_as": "busy",
            "authoritative": True,
            "category_name": "Salt",
            "source": "synthetic_prove",
        }
    ]
    discovery_slots = session_slots_for_resource(
        date_str=TUE,
        weekly_hours=NICHOLE_HOURS,
        busy_intervals=[],  # Salt busy not applied to Nichole
        prep_minutes=0,
        session_minutes=30,
        recovery_minutes=15,
        start_increment_minutes=60,
        flags={"no_mondays": True},
    )
    salt_slots = session_slots_for_resource(
        date_str=TUE,
        weekly_hours=SALT_HOURS,
        busy_intervals=salt_busy,
        prep_minutes=0,
        session_minutes=SALT_SESSION,
        recovery_minutes=SALT_RECOVERY,
        start_increment_minutes=60,
        last_start_time=SALT_LAST_START,
    )
    _check(
        "P3-core",
        "15:00" in _starts(discovery_slots),
        "Discovery still offers 15:00 when only Salt is busy",
        failures,
    )
    _check(
        "P3-core-salt",
        "15:00" not in _starts(salt_slots),
        "Salt 15:00 removed when room busy 15:00–16:00",
        failures,
    )
    return failures


def prove_monday_discovery_closed_salt_open() -> List[str]:
    """P4-core: Monday Discovery empty; Salt still offers Mon–Fri hours."""
    failures: List[str] = []
    discovery_slots = session_slots_for_resource(
        date_str=MON,
        weekly_hours=NICHOLE_HOURS_WITH_MON,
        busy_intervals=[],
        prep_minutes=0,
        session_minutes=30,
        recovery_minutes=15,
        start_increment_minutes=60,
        flags={"no_mondays": True},
    )
    salt_slots = session_slots_for_resource(
        date_str=MON,
        weekly_hours=SALT_HOURS,
        busy_intervals=[],
        prep_minutes=0,
        session_minutes=SALT_SESSION,
        recovery_minutes=SALT_RECOVERY,
        start_increment_minutes=60,
        last_start_time=SALT_LAST_START,
    )
    _check(
        "P4-core-discovery",
        discovery_slots == [],
        "Monday Discovery has no slots (no_mondays)",
        failures,
    )
    _check(
        "P4-core-salt",
        bool(salt_slots) and salt_slots[0]["start_time"] == "11:00",
        "Monday Salt still offers from 11:00 (10:30 open; hourly grid)",
        failures,
    )
    _check(
        "P4-core-salt-last",
        bool(salt_slots) and salt_slots[-1]["start_time"] == SALT_LAST_START,
        f"Monday Salt last start is {SALT_LAST_START}",
        failures,
    )
    return failures


def _default_artifact_path() -> Path:
    repo_root = _THIS_DIR.parent.parent
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return repo_root / "qa" / "reports" / "multi-resource-proof" / f"prove-in-process-{stamp}.json"


def _write_artifact(
    *,
    path: Path,
    failures: List[str],
    checks_passed: int,
) -> None:
    payload = {
        "kind": "prove_multi_resource_slots_in_process",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "multi_resource_scheduling": MULTI_RESOURCE_SCHEDULING,
        "result": "pass" if not failures else "fail",
        "checks_passed": checks_passed,
        "failures": failures,
        "scope": "synthetic P1-P4 core; not production Mongo or Cloud Run",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="In-process Discovery≠Salt prove (no Mongo).")
    parser.add_argument(
        "--write-artifact",
        nargs="?",
        const="auto",
        default=None,
        help="Write JSON under qa/reports/multi-resource-proof/ (optional path)",
    )
    args = parser.parse_args()

    print("=== prove_multi_resource_slots (in-process; no prod) ===")
    print(f"  MULTI_RESOURCE_SCHEDULING={MULTI_RESOURCE_SCHEDULING}")
    if MULTI_RESOURCE_SCHEDULING:
        print(
            "  WARN: flag is true — prove script is still synthetic-only; "
            "do not treat this as production cutover."
        )
    else:
        print("  NOTE: flag false — booking/Outlook paths ignore multi_resource_slots.")

    failures: List[str] = []
    print("\n-- Discovery ≠ Salt (P1/P2 core) --")
    failures.extend(prove_discovery_neq_salt())
    print("\n-- Salt ≠ Discovery (P3 core) --")
    failures.extend(prove_salt_neq_discovery())
    print("\n-- Monday Discovery closed / Salt open (P4 core) --")
    failures.extend(prove_monday_discovery_closed_salt_open())

    checks_passed = 7 - len(failures)
    if args.write_artifact is not None:
        artifact_path = (
            _default_artifact_path()
            if args.write_artifact == "auto"
            else Path(args.write_artifact)
        )
        _write_artifact(path=artifact_path, failures=failures, checks_passed=checks_passed)
        print(f"  artifact: {artifact_path}")

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} check(s))")
        for item in failures:
            print(f"  - {item}")
        return 1

    print("RESULT: PASS — Discovery ≠ Salt invariant holds in-process")
    return 0


if __name__ == "__main__":
    sys.exit(main())
