"""Durable per-ingest public collector ceilings; a crash never refunds work.

Only admission records are written here. No source check or operational deferral
can be invented by the budget controller. All SQL parameters are local identities.
"""
from __future__ import annotations

import math
import secrets
import sqlite3
import time
from dataclasses import dataclass

from cdr_terms.identity import digest, utc_now

MAX_INGEST_BYTES = 64 * 1024**2
MAX_INGEST_MS = 300000
MAX_DOCUMENT_BYTES = 16 * 1024**2
MAX_SLICE_SECONDS = 105
SUPERVISOR_MS = 120000
MIN_DEADLINE_MS = 1000


class BudgetDeferred(RuntimeError):
    pass


def usage(store, ingest_id: str) -> dict:
    row = store.db.execute(
        "SELECT COALESCE(SUM(COALESCE(s.charged_bytes,r.reserved_bytes)),0) bytes, "
        "COALESCE(SUM(COALESCE(s.charged_ms,r.reserved_ms)),0) milliseconds "
        "FROM public_rate_budget_reservations r LEFT JOIN public_rate_budget_settlements s USING(reservation_id) "
        "WHERE r.ingest_id=?", (ingest_id,)).fetchone()
    return {"bytes": row["bytes"], "milliseconds": row["milliseconds"]}


def reason(store, ingest_id: str, *, need_bytes: bool = False) -> str | None:
    used = usage(store, ingest_id)
    if used["milliseconds"] > MAX_INGEST_MS - SUPERVISOR_MS:
        return "public_rate_ingest_time_budget"
    if need_bytes and used["bytes"] > MAX_INGEST_BYTES - MAX_DOCUMENT_BYTES:
        return "public_rate_ingest_byte_budget"
    return None


def available_sql(alias: str, *, bytes_required: bool) -> str:
    # The alias is a checked-in caller literal, never source material.
    if alias not in {"r", "e"}:
        raise ValueError("invalid_budget_sql_alias")
    time_sum = ("(SELECT COALESCE(SUM(COALESCE(bs.charged_ms,br.reserved_ms)),0) "
                "FROM public_rate_budget_reservations br LEFT JOIN public_rate_budget_settlements bs "
                f"USING(reservation_id) WHERE br.ingest_id={alias}.ingest_id)")
    clause = time_sum + "<=180000"
    if bytes_required:
        clause += (" AND (SELECT COALESCE(SUM(COALESCE(bs.charged_bytes,br.reserved_bytes)),0) "
                   "FROM public_rate_budget_reservations br LEFT JOIN public_rate_budget_settlements bs "
                   f"USING(reservation_id) WHERE br.ingest_id={alias}.ingest_id)<=50331648")
    return "(" + clause + ")"


@dataclass
class Reservation:
    store: object
    reservation_id: str
    ingest_id: str
    reserved_bytes: int
    reserved_ms: int
    started: float
    deadline: float
    guard: object = None

    def __enter__(self):
        self.checkpoint()
        if not hasattr(self, "_previous_stack"):
            self._previous_stack = []
        self._previous_stack.append(getattr(self.store, "_public_rate_progress", None))
        self.store._public_rate_progress = self
        self.store.db.set_progress_handler(lambda: int(time.monotonic() >= self.deadline), 1000)
        return self

    def __exit__(self, kind, value, traceback):
        previous = self._previous_stack.pop()
        self.store._public_rate_progress = previous
        self.store.db.set_progress_handler((lambda: int(time.monotonic() >= previous.deadline)) if previous else None, 1000 if previous else 0)
        if isinstance(value, sqlite3.OperationalError) and time.monotonic() >= self.deadline:
            raise BudgetDeferred("public_rate_slice_deadline") from value
        return False

    def checkpoint(self) -> None:
        if time.monotonic() >= self.deadline:
            raise BudgetDeferred("public_rate_slice_deadline")
        if self.guard:
            value = self.guard()
            if value:
                raise BudgetDeferred("public_rate_operational_guard:" + str(value))

    def settle(self, *, body_bytes: int | None = None, check_id: str | None = None) -> None:
        charged = self.reserved_bytes if body_bytes is None else body_bytes
        if type(charged) is not int or not 0 <= charged <= self.reserved_bytes:
            raise ValueError("invalid_public_rate_budget_settlement")
        elapsed = max(1, math.ceil((time.monotonic() - self.started) * 1000))
        # Keep an honest overshoot visible and prevent any further admission.
        # The existing supervised worker remains the hard process boundary.
        milliseconds = elapsed
        values = (self.reservation_id, charged, milliseconds, utc_now(), check_id)
        with self.store.db:
            prior = self.store.db.execute("SELECT * FROM public_rate_budget_settlements WHERE reservation_id=?",
                                          (self.reservation_id,)).fetchone()
            if prior:
                raise ValueError("public_rate_budget_already_settled")
            self.store.db.execute("INSERT INTO public_rate_budget_settlements VALUES (?,?,?,?,?)", values)


def reserve(store, ingest_id: str, *, kind: str, seconds: float = MAX_SLICE_SECONDS,
            body_bytes: int = 0, work_id: str | None = None, deadline: float | None = None,
            guard=None) -> Reservation:
    if kind not in {"capture", "source", "candidate"} or not math.isfinite(seconds) or not 0 < seconds <= MAX_SLICE_SECONDS:
        raise ValueError("invalid_public_rate_budget_request")
    if type(body_bytes) is not int or not 0 <= body_bytes <= MAX_INGEST_BYTES:
        raise ValueError("invalid_public_rate_byte_request")

    def admit():
        started = time.monotonic()
        stop_at = started + seconds if deadline is None else min(deadline, started + seconds)
        remaining = usage(store, ingest_id)
        if MAX_INGEST_MS - remaining["milliseconds"] < SUPERVISOR_MS:
            raise BudgetDeferred("public_rate_ingest_time_budget")
        if math.floor((stop_at - started) * 1000) < MIN_DEADLINE_MS:
            raise BudgetDeferred("public_rate_slice_deadline")
        allowance_ms = SUPERVISOR_MS
        allowance_bytes = body_bytes
        if body_bytes > MAX_INGEST_BYTES - remaining["bytes"]:
            raise BudgetDeferred("public_rate_ingest_byte_budget")
        identity = work_id or secrets.token_hex(32)
        reservation_id = digest([ingest_id, identity, kind])
        store.db.execute("INSERT INTO public_rate_budget_reservations VALUES (?,?,?,?,?,?,?)",
                         (reservation_id, ingest_id, identity, kind, allowance_bytes, allowance_ms, utc_now()))
        return Reservation(store, reservation_id, ingest_id, allowance_bytes, allowance_ms,
                           started, stop_at, guard)

    if store.db.in_transaction:
        return admit()
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        return admit()
