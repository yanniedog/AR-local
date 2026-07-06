"""Shared constants and helpers for the mobile-app payload builder."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent

SCHEMA_VERSION = 1
DEFAULT_REPO = os.environ.get("AR_LOCAL_REPO", "yanniedog/AR-local")
DEFAULT_TAG = os.environ.get("AR_LOCAL_APP_PAYLOAD_TAG", "app-payload-latest")
DATED_TAG_PREFIX = "app-payload-"
DATES_INDEX_FILENAME = "dates-index.json"
HISTORY_MIN_DATE = "2026-05-13"
_RUN_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
APP_MIN_VERSION = "1.0.0"
# Bound every gh subprocess so a network/CLI stall can never hang the Pi's daily
# pipeline. Uploads get a longer budget than metadata calls.
SUBPROCESS_TIMEOUT_SEC = 30
SUBPROCESS_UPLOAD_TIMEOUT_SEC = 600
# Content-addressed assets accumulate on the rolling release; GitHub caps a release at
# 1000 assets. Keep the current manifest's assets plus a recent buffer (covers any
# in-flight client still holding the just-superseded manifest) and prune older ones.
KEEP_RECENT_ASSETS = 48  # backfill window (~2 assets/day)
MAX_EMBEDDED_LOGO_BYTES = 64 * 1024

VALID_SECTIONS = ("Mortgage", "Savings", "TD")

# Curated subset of the flattened rate-row columns (a superset of the dashboard's
# BANK_SECTION_COLUMNS, plus comparison_rate / last_updated which banks.json carries
# but the section API drops). Empty values are stripped per-row before encoding.
CORE_RATE_FIELDS = (
    "provider",
    "product_id",
    "product_key",
    "product_name",
    "category",
    "rate",
    "comparison_rate",
    "rate_type",
    "repayment_type",
    "loan_purpose",
    "term",
    "term_months",
    "lvr_tier",
    "ribbon_normalized",
    "security_purpose",
    "ribbon_repayment_type",
    "ribbon_rate_structure",
    "ribbon_fixed_term",
    "account_type",
    "ribbon_deposit_kind",
    "balance_min",
    "balance_max",
    "interest_payment",
    "feature_set",
    "account_class",
    "rate_index",
    "last_updated",
    "taxonomy_path",  # dot-delimited hierarchy that drives the app's drill-down tree
)


# --------------------------------------------------------------------------- #
# Small shared helpers
# --------------------------------------------------------------------------- #
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def compact(row: Dict[str, Any]) -> Dict[str, Any]:
    """Drop absent/empty fields before JSON encoding (matches the dashboard)."""
    return {key: value for key, value in row.items() if not _is_blank(value)}


def section_filter(dataset: str, row: Dict[str, Any]) -> bool:
    """Mirror cdr_dashboard_server.bank_section_rate_filter."""
    rate = row.get("rate")
    if _is_blank(rate):
        return False
    family = row.get("rate_family")
    if dataset == "Mortgage":
        return family == "lending" and (row.get("rate_type") or "") != "DISCOUNT"
    return family == "deposit"



def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))




def dated_tag(run_date: str) -> str:
    """Immutable per-run_date release tag (``app-payload-YYYY-MM-DD``)."""
    if not _RUN_DATE_RE.match(run_date):
        raise ValueError(f"invalid run_date for dated tag: {run_date!r}")
    return f"{DATED_TAG_PREFIX}{run_date}"


def is_rolling_tag(tag: str) -> bool:
    """True for the canonical rolling latest tag the mobile app polls."""
    return tag in (DEFAULT_TAG, "app-payload-latest")


def is_dated_tag(tag: str) -> bool:
    """True for immutable per-run_date snapshot tags."""
    if not tag.startswith(DATED_TAG_PREFIX):
        return False
    return bool(_RUN_DATE_RE.match(tag[len(DATED_TAG_PREFIX) :]))


def release_title(run_date: str) -> str:
    """Human-readable rolling-release title for a given payload run_date."""
    return f"Australian Rates payload — latest ({run_date})"


def dated_release_title(run_date: str) -> str:
    """Human-readable title for an immutable per-run_date snapshot release."""
    return f"Australian Rates payload — {run_date}"


def release_display_title(tag: str, run_date: str) -> str:
    """GitHub release title for ``tag`` using manifest ``run_date``."""
    return release_title(run_date) if is_rolling_tag(tag) else dated_release_title(run_date)


def _app_payload(name: str):
    """Resolve a symbol from the app_payload facade (supports test monkeypatch)."""
    import importlib

    return getattr(importlib.import_module("app_payload"), name)
