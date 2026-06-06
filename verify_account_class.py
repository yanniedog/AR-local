#!/usr/bin/env python3
"""Self-test for cdr_taxonomy.classify_account_standardness.

Standalone (no pytest dependency) to match this repo's verify_* convention.
Asserts that mainstream retail products classify as 'standard' while
foreign-currency, farm, business, trust/SMSF and other non-standard accounts —
plus any unknown/future CDR product category — classify as 'non_standard'.
Exit 0 on pass, 1 on failure.

Run: python verify_account_class.py
"""
from __future__ import annotations

import sys

from cdr_taxonomy import (
    ACCOUNT_CLASS_NON_STANDARD,
    ACCOUNT_CLASS_STANDARD,
    classify_account_standardness,
)

# (product_name, category, expected, why)
CASES: list[tuple[str, str, str, str]] = [
    # --- Standard mainstream retail ----------------------------------------
    ("NetBank Saver", "TRANS_AND_SAVINGS_ACCOUNTS", ACCOUNT_CLASS_STANDARD, "plain online saver"),
    ("Everyday Account Smart Access", "TRANS_AND_SAVINGS_ACCOUNTS", ACCOUNT_CLASS_STANDARD, "transaction acct"),
    ("GoalSaver", "TRANS_AND_SAVINGS_ACCOUNTS", ACCOUNT_CLASS_STANDARD, "bonus saver brand name"),
    ("Term Deposit", "TERM_DEPOSITS", ACCOUNT_CLASS_STANDARD, "vanilla TD"),
    ("Standard Variable Home Loan", "RESIDENTIAL_MORTGAGES", ACCOUNT_CLASS_STANDARD, "home loan"),
    ("Low Rate Credit Card", "CRED_AND_CHRG_CARDS", ACCOUNT_CLASS_STANDARD, "credit card"),
    ("Personal Loan", "PERS_LOANS", ACCOUNT_CLASS_STANDARD, "personal loan"),
    # False-positive guards: generic markers must not match inside unrelated words
    # or collide with Australian mutual-ADI brand names (building societies, etc.).
    ("Platform Saver", "TRANS_AND_SAVINGS_ACCOUNTS", ACCOUNT_CLASS_STANDARD, "'farm' inside 'Platform'"),
    ("Community First Credit Union Pocket Saver", "TRANS_AND_SAVINGS_ACCOUNTS", ACCOUNT_CLASS_STANDARD, "mutual brand, not an org account"),
    ("Greater Building Society Select Saver", "TRANS_AND_SAVINGS_ACCOUNTS", ACCOUNT_CLASS_STANDARD, "building society brand"),
    # --- Non-standard by NAME (mis-filed under a standard category) ---------
    ("Foreign Currency Account (Retail)", "TRANS_AND_SAVINGS_ACCOUNTS", ACCOUNT_CLASS_NON_STANDARD, "FX — the CBA incident"),
    ("FX Settlement Account", "TRANS_AND_SAVINGS_ACCOUNTS", ACCOUNT_CLASS_NON_STANDARD, "fx token"),
    ("Farm Management Deposit", "TERM_DEPOSITS", ACCOUNT_CLASS_NON_STANDARD, "farm / FMD"),
    ("AgriBusiness Cash Account", "TRANS_AND_SAVINGS_ACCOUNTS", ACCOUNT_CLASS_NON_STANDARD, "agribusiness"),
    ("Business Transaction Account", "TRANS_AND_SAVINGS_ACCOUNTS", ACCOUNT_CLASS_NON_STANDARD, "business"),
    ("Commercial Term Deposit", "TERM_DEPOSITS", ACCOUNT_CLASS_NON_STANDARD, "commercial"),
    ("SMSF Cash Hub", "TRANS_AND_SAVINGS_ACCOUNTS", ACCOUNT_CLASS_NON_STANDARD, "smsf"),
    ("Statutory Trust Account", "TRANS_AND_SAVINGS_ACCOUNTS", ACCOUNT_CLASS_NON_STANDARD, "trust"),
    ("Sailing Club Account", "TRANS_AND_SAVINGS_ACCOUNTS", ACCOUNT_CLASS_NON_STANDARD, "club / org account"),
    ("Non-Resident Savings", "TRANS_AND_SAVINGS_ACCOUNTS", ACCOUNT_CLASS_NON_STANDARD, "non-resident"),
    ("At Call Account", "TRANS_AND_SAVINGS_ACCOUNTS", ACCOUNT_CLASS_NON_STANDARD, "at-call savings"),
    # --- Non-standard LENDING filed under RESIDENTIAL_MORTGAGES ----------------
    ("Green Home Loan", "RESIDENTIAL_MORTGAGES", ACCOUNT_CLASS_NON_STANDARD, "RACQ clean-energy loan"),
    ("Home Equity Maximiser Investment", "RESIDENTIAL_MORTGAGES", ACCOUNT_CLASS_NON_STANDARD, "equity line of credit"),
    ("Bridging Loan", "RESIDENTIAL_MORTGAGES", ACCOUNT_CLASS_NON_STANDARD, "bridging finance"),
    ("Land Loan", "RESIDENTIAL_MORTGAGES", ACCOUNT_CLASS_NON_STANDARD, "land loan"),
    ("Construction Loan", "RESIDENTIAL_MORTGAGES", ACCOUNT_CLASS_NON_STANDARD, "construction loan"),
    ("Solar Upgrade Loan", "RESIDENTIAL_MORTGAGES", ACCOUNT_CLASS_NON_STANDARD, "solar"),
    # Guard: 'green'/'land' markers must not collide with mainstream brand/product names.
    ("Greater Bank Variable Home Loan", "RESIDENTIAL_MORTGAGES", ACCOUNT_CLASS_STANDARD, "'green' not in 'Greater'"),
    ("Maitland Mutual Home Loan", "RESIDENTIAL_MORTGAGES", ACCOUNT_CLASS_STANDARD, "'land' not in 'Maitland'"),
    # --- Non-standard by CATEGORY (future-proofing) ------------------------
    # Neutral name (no marker) so this genuinely exercises the category path:
    # BUSINESS_LOANS must NOT be a standard category.
    ("Equipment Finance", "BUSINESS_LOANS", ACCOUNT_CLASS_NON_STANDARD, "business loan, neutral name -> category catch"),
    ("CommSec Margin Loan", "MARGIN_LOANS", ACCOUNT_CLASS_NON_STANDARD, "margin loan category"),
    ("Trade Finance Facility", "TRADE_FINANCE", ACCOUNT_CLASS_NON_STANDARD, "trade finance category"),
    # A brand-new account whose category the CDR has not published before and
    # whose name carries no known marker must STILL be caught as non-standard.
    ("Acme Quantum Vault", "QUANTUM_DEPOSITS", ACCOUNT_CLASS_NON_STANDARD, "unknown future category"),
    # --- Defensive: empties -------------------------------------------------
    ("", "", ACCOUNT_CLASS_STANDARD, "no signal -> standard"),
]


def main() -> int:
    failures: list[str] = []
    for name, category, expected, why in CASES:
        got = classify_account_standardness(name, category)
        if got != expected:
            failures.append(
                f"{why}: classify({name!r}, {category!r}) = {got!r}, expected {expected!r}"
            )

    # A name marker must win even when the category looks standard (the FX case).
    if classify_account_standardness("Foreign Currency Account", "SAVINGS") != ACCOUNT_CLASS_NON_STANDARD:
        failures.append("name marker should override a standard category")

    if failures:
        print("FAIL verify_account_class:")
        for line in failures:
            print("  -", line)
        return 1
    print(f"PASS verify_account_class: {len(CASES)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
