"""Append-only ledger enforcement in cdr_daily.resolve_ledger_target.

Encodes the Permanent CDR Ledger Invariant at the one code path that can reach
finalized ledger bytes: the daily ingest's write target. Today's partition stays
mutable; past days are immutable (force => revision, missing gap => refuse).
"""

from datetime import datetime

import pytest

import cdr_daily

TODAY = "2026-06-16"


def _finalize(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "local-cdr.sqlite").write_bytes(b"finalized")
    return root


def test_today_writes_primary(tmp_path):
    primary = tmp_path / TODAY / "_exports"
    target, is_revision = cdr_daily.resolve_ledger_target(primary, TODAY, TODAY, force=False)
    assert target == primary
    assert is_revision is False


def test_future_date_writes_primary(tmp_path):
    primary = tmp_path / "2026-12-31" / "_exports"
    target, is_revision = cdr_daily.resolve_ledger_target(primary, "2026-12-31", TODAY, force=False)
    assert target == primary and is_revision is False


def test_finalized_past_day_refuses_overwrite_without_force(tmp_path):
    primary = _finalize(tmp_path / "2026-05-13" / "_exports")
    with pytest.raises(cdr_daily.LedgerImmutabilityError, match="overwrite finalized ledger day"):
        cdr_daily.resolve_ledger_target(primary, "2026-05-13", TODAY, force=False)
    # The original bytes are untouched by the (refused) call.
    assert (primary / "local-cdr.sqlite").read_bytes() == b"finalized"


def test_finalized_past_day_force_appends_revision(tmp_path):
    primary = _finalize(tmp_path / "2026-05-13" / "_exports")
    when = datetime(2026, 6, 16, 9, 30, 0)
    target, is_revision = cdr_daily.resolve_ledger_target(
        primary, "2026-05-13", TODAY, force=True, now=when
    )
    assert is_revision is True
    # Revision is a sibling under _revisions/<stamp>/_exports, never the primary.
    assert target == primary.parent / "_revisions" / "20260616T093000" / "_exports"
    assert target != primary
    assert (primary / "local-cdr.sqlite").read_bytes() == b"finalized"


def test_missing_past_day_is_never_fabricated(tmp_path):
    # The 2026-05-14 gap: no primary content. Live data must not be written here,
    # with or without --force.
    primary = tmp_path / "2026-05-14" / "_exports"
    for force in (False, True):
        with pytest.raises(cdr_daily.LedgerImmutabilityError, match="gap must remain a gap"):
            cdr_daily.resolve_ledger_target(primary, "2026-05-14", TODAY, force=force)
    assert not primary.exists()


def test_empty_past_export_dir_counts_as_gap(tmp_path):
    # An empty (but existing) _exports dir is not a finalized day.
    primary = (tmp_path / "2026-05-14" / "_exports")
    primary.mkdir(parents=True)
    with pytest.raises(cdr_daily.LedgerImmutabilityError, match="gap must remain a gap"):
        cdr_daily.resolve_ledger_target(primary, "2026-05-14", TODAY, force=True)


def test_revision_root_for_structure(tmp_path):
    primary = tmp_path / "2026-05-13" / "_exports"
    rev = cdr_daily.revision_root_for(primary, datetime(2026, 6, 16, 1, 2, 3))
    assert rev == primary.parent / "_revisions" / "20260616T010203" / "_exports"
