#!/usr/bin/env python3
"""Ingest-timer state checks for Pi deploy verify.

Kept separate from ``pi_deploy_verify.py`` so held-timer and arming checks
stay within the repo modularity ceiling.
"""

from __future__ import annotations

import sys
from typing import Mapping

INGEST_TIMER_FIELDS = (
    "DAILY_TIMER_ENABLED",
    "DAILY_TIMER_ACTIVE",
    "WATCHDOG_TIMER_ENABLED",
    "WATCHDOG_TIMER_ACTIVE",
    "CAPACITY_TIMER_ENABLED",
    "CAPACITY_TIMER_ACTIVE",
)

INGEST_TIMER_ARMED = {
    "DAILY_TIMER_ENABLED": "enabled",
    "DAILY_TIMER_ACTIVE": "active",
    "WATCHDOG_TIMER_ENABLED": "enabled",
    "WATCHDOG_TIMER_ACTIVE": "active",
    "CAPACITY_TIMER_ENABLED": "enabled",
    "CAPACITY_TIMER_ACTIVE": "active",
}

INGEST_TIMER_UNARMED = {
    "DAILY_TIMER_ENABLED": "disabled",
    "DAILY_TIMER_ACTIVE": "inactive",
    "WATCHDOG_TIMER_ENABLED": "disabled",
    "WATCHDOG_TIMER_ACTIVE": "inactive",
    "CAPACITY_TIMER_ENABLED": "disabled",
    "CAPACITY_TIMER_ACTIVE": "inactive",
}


def print_ingest_timer_fields(snap: Mapping[str, str]) -> None:
    for field in INGEST_TIMER_FIELDS:
        print(f"pi_deploy_verify: {field}: {snap.get(field, '')}")


def pi_ingest_timer_fields_observed(snap: Mapping[str, str]) -> bool:
    """True when every ingest-timer field is present and non-empty."""
    missing = [field for field in INGEST_TIMER_FIELDS if not str(snap.get(field, "")).strip()]
    if missing:
        print(
            "pi_deploy_verify: ingest timer state missing or unreadable: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        return False
    return True


def pi_ingest_timers_ok(snap: Mapping[str, str]) -> bool:
    print_ingest_timer_fields(snap)
    ok = all(snap.get(field, "") == value for field, value in INGEST_TIMER_ARMED.items())
    if not ok:
        print("pi_deploy_verify: daily ingest timers are not armed", file=sys.stderr)
    return ok


def pi_ingest_timers_allow_unarmed(snap: Mapping[str, str]) -> bool:
    """Held-timer verify: require observed state; allow armed or explicitly unarmed."""
    print_ingest_timer_fields(snap)
    if not pi_ingest_timer_fields_observed(snap):
        return False
    if all(snap.get(field, "") == value for field, value in INGEST_TIMER_ARMED.items()):
        return True
    if all(snap.get(field, "") == value for field, value in INGEST_TIMER_UNARMED.items()):
        return True
    print(
        "pi_deploy_verify: ingest timers are neither fully armed nor fully unarmed "
        "(held-timer bypass requires an explicit observed state)",
        file=sys.stderr,
    )
    return False
