"""Tests for staff/occupation restriction → non-standard classification."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from cdr_taxonomy import classify_account_standardness as clf  # noqa: E402


def test_staff_only_product_name_is_non_standard():
    # Coastline "Staff Housing Loan" / People First "Staff Home Loan": staff-only,
    # not open to the public — must be confined to the non-standard filter.
    assert clf("Staff Housing Loan", "RESIDENTIAL_MORTGAGES", "Mortgage") == "non_standard"
    assert clf("People First and Heritage Staff Home Loan", "RESIDENTIAL_MORTGAGES", "Mortgage") == "non_standard"
    # Staff-only deposit/transaction accounts (not just home loans) too.
    assert clf("Staff Saver", "TRANS_AND_SAVINGS_ACCOUNTS", "Savings") == "non_standard"
    assert clf("Employee Everyday Account", "TRANS_AND_SAVINGS_ACCOUNTS", "Savings") == "non_standard"


@pytest.mark.parametrize("code", ["STAFF", "staff", " Staff ", "StAfF"])
def test_staff_eligibility_type_code_is_robust_to_formatting(code):
    elig = [{"eligibilityType": code}]
    assert clf("Premium Package Home Loan", "RESIDENTIAL_MORTGAGES", "Mortgage", eligibility=elig) == "non_standard"


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


def test_employee_phrasing_in_eligibility_text_stays_standard():
    # "staff"/"employee" are matched on the product NAME only — ordinary lending
    # criteria like "must be a permanent employee" must NOT flip a retail product.
    for info in ("Must be a permanent employee", "Applicant must be a full-time employee"):
        elig = [{"eligibilityType": "OTHER", "additionalInfo": info}]
        assert clf("Basic Variable Home Loan", "RESIDENTIAL_MORTGAGES", "Mortgage", eligibility=elig) == "standard"


def test_negated_staff_eligibility_text_stays_standard():
    elig = [{"eligibilityType": "OTHER", "additionalInfo": "Not available to staff of the bank"}]
    assert clf("Everyday Home Loan", "RESIDENTIAL_MORTGAGES", "Mortgage", eligibility=elig) == "standard"


def test_plain_retail_product_is_standard():
    assert clf("Basic Variable Home Loan", "RESIDENTIAL_MORTGAGES", "Mortgage") == "standard"


# --- Employer/occupation-restricted memberships (genuinely closed cohorts) --- #

@pytest.mark.parametrize(
    "info",
    [
        "You must be a member. Membership is open to current or retired employees of the Australian education sector",
        "Membership is open to team members of Woolworths and Endeavour Groups, their immediate family",
        "Membership is open to current or former employees of police, ambulance, firies, health workers",
        "Border Value Home Loan only available to current serving Border Officers or a Retired Border Officer",
        "The card is only available to employees who work for an eligible employer",
        "Need to be employed by an eligible employer.",
        "Available to ADF members who are within 12 Months either side of milestones.",
    ],
)
def test_employer_or_occupation_membership_is_non_standard(info):
    elig = [{"eligibilityType": "OTHER", "additionalInfo": info}, {"eligibilityType": "RESIDENCY_STATUS"}]
    assert clf("Your Way Fixed Rate Home Loan", "RESIDENTIAL_MORTGAGES", "Mortgage", eligibility=elig) == "non_standard"


def test_open_membership_path_suppresses_employer_flag():
    # A product that lists an employer cohort AND an open path (anyone resident in
    # Australia can join) is open to the public — must stay standard.
    elig = [
        {"eligibilityType": "OTHER", "additionalInfo": "Membership is open to employees of the rail industry"},
        {"eligibilityType": "OTHER", "additionalInfo": "or to citizens or permanent residents of Australia"},
    ]
    assert clf("Everyday Saver", "TRANS_AND_SAVINGS_ACCOUNTS", "Savings", eligibility=elig) == "standard"


@pytest.mark.parametrize(
    "info",
    [
        "Must be a member of the Credit Union",
        "This product is only available to members who have a residential address in Australia",
        "You do not have to be a member to hold a term deposit",
        "Qantas Point Saver is only available to personal members",
    ],
)
def test_open_membership_credit_union_stays_standard(info):
    # Bare "member of the Credit Union" (open membership) and Australian-resident
    # availability must NOT be flagged.
    elig = [{"eligibilityType": "OTHER", "additionalInfo": info}]
    assert clf("Bonus Saver", "TRANS_AND_SAVINGS_ACCOUNTS", "Savings", eligibility=elig) == "standard"


def test_negated_employer_membership_stays_standard():
    elig = [{"eligibilityType": "OTHER", "additionalInfo": "Not available to employees of the bank"}]
    assert clf("Everyday Saver", "TRANS_AND_SAVINGS_ACCOUNTS", "Savings", eligibility=elig) == "standard"


def test_open_and_closed_membership_in_same_item_stays_standard():
    # Both the employer cohort and an open path in ONE eligibility string.
    elig = [{
        "eligibilityType": "OTHER",
        "additionalInfo": "Membership is open to employees of the rail industry or to citizens "
        "or permanent residents of Australia",
    }]
    assert clf("Everyday Saver", "TRANS_AND_SAVINGS_ACCOUNTS", "Savings", eligibility=elig) == "standard"


def test_bare_residency_requirement_does_not_suppress_employer_restriction():
    # A normal RESIDENCY_STATUS row ("must be a resident of Australia") is NOT an
    # open-membership alternative — a closed employer cohort with such a row must
    # still be flagged (otherwise the restriction leaks).
    elig = [
        {"eligibilityType": "OTHER", "additionalInfo": "Membership is open to employees of the Australian education sector"},
        {"eligibilityType": "RESIDENCY_STATUS", "additionalInfo": "Applicants must be permanent residents of Australia"},
    ]
    assert clf("Your Way Fixed Rate Home Loan", "RESIDENTIAL_MORTGAGES", "Mortgage", eligibility=elig) == "non_standard"
