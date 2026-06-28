"""Tests for staff/occupation restriction → non-standard classification."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cdr_taxonomy import classify_account_standardness as clf  # noqa: E402


def test_staff_only_product_name_is_non_standard():
    # Coastline "Staff Housing Loan" / People First "Staff Home Loan": staff-only,
    # not open to the public — must be confined to the non-standard filter.
    assert clf("Staff Housing Loan", "RESIDENTIAL_MORTGAGES", "Mortgage") == "non_standard"
    assert clf("People First and Heritage Staff Home Loan", "RESIDENTIAL_MORTGAGES", "Mortgage") == "non_standard"


def test_staff_eligibility_type_code_is_non_standard_even_with_ordinary_name():
    # Some staff products have an ordinary name but carry the STAFF eligibility code.
    elig = [{"eligibilityType": "MIN_AGE"}, {"eligibilityType": "STAFF"}]
    assert clf("Premium Package Home Loan", "RESIDENTIAL_MORTGAGES", "Mortgage", eligibility=elig) == "non_standard"


def test_essential_worker_program_name_is_non_standard():
    assert clf("Essential Worker Home Loan - Owner Occupied", "RESIDENTIAL_MORTGAGES", "Mortgage") == "non_standard"
    assert clf("First Responder Saver", "TRANS_AND_SAVINGS_ACCOUNTS", "Savings") == "non_standard"


def test_occupation_brand_in_name_stays_standard():
    # "Police Bank", "Firefighters Mutual", "Nurses & Midwives" are ADI brands —
    # their ordinary products must NOT be flagged on the brand word.
    assert clf("Police Bank Goal Saver", "TRANS_AND_SAVINGS_ACCOUNTS", "Savings") == "standard"
    assert clf("Firefighters Mutual Everyday Account", "TRANS_AND_SAVINGS_ACCOUNTS", "Savings") == "standard"


def test_employment_status_alone_does_not_flag():
    # EMPLOYMENT_STATUS can mean "employed/PAYG income" — too general to flag on
    # the code alone (real occupation cohorts are caught via name/free-text).
    elig = [{"eligibilityType": "EMPLOYMENT_STATUS", "additionalInfo": "Applicant earns PAYG income"}]
    assert clf("Basic Variable Home Loan", "RESIDENTIAL_MORTGAGES", "Mortgage", eligibility=elig) == "standard"


def test_negated_staff_eligibility_text_stays_standard():
    elig = [{"eligibilityType": "OTHER", "additionalInfo": "Not available to staff of the bank"}]
    assert clf("Everyday Home Loan", "RESIDENTIAL_MORTGAGES", "Mortgage", eligibility=elig) == "standard"


def test_plain_retail_product_is_standard():
    assert clf("Basic Variable Home Loan", "RESIDENTIAL_MORTGAGES", "Mortgage") == "standard"
