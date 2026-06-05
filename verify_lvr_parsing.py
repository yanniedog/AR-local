#!/usr/bin/env python3
"""Self-test for cdr_ribbon_normalize.named_lvr_tier and the resolve_lvr_tier
fallback that reads LVR/LTV stated as a bare number (no % sign).

Standalone (no pytest) to match this repo's verify_* convention. Background:
products like Cairns Bank "CLASSIC HOME LOAN VARIABLE <60 LVR IO" / "... >90 LVR
PI" encode the LVR band in the name with plain </> operators and no % — the
%-anchored parsers missed them, dumping the rows into lvr_unspecified.

Run: python verify_lvr_parsing.py
"""
from __future__ import annotations

import sys

from cdr_ribbon_normalize import named_lvr_tier, resolve_lvr_tier

# (text, expected_tier, why)
NAMED_CASES = [
    ("CLASSIC HOME LOAN VARIABLE <60 LVR IO", "lvr_=60%", "<60 upper bound"),
    ("CLASSIC HOME LOAN VARIABLE >90 LVR PI", "lvr_90-95%", ">90 bumps to top tier"),
    ("Owner Occupied 70-80 LVR PI", "lvr_70-80%", "range upper bound"),
    ("Investment LVR up to 85", "lvr_80-85%", "'up to 85'"),
    ("LVR <= 80%", "lvr_70-80%", "<=80 with %"),
    (">80 LVR", "lvr_80-85%", ">80 bumps one tier"),
    ("LVR 95", "lvr_90-95%", "bare 'LVR 95'"),
    ("80 LVR", "lvr_70-80%", "bare number before LVR, no operator"),
    ("LVR less than 70", "lvr_60-70%", "natural-language 'less than'"),
    ("greater than 90 LVR", "lvr_90-95%", "natural-language 'greater than' bumps up"),
    ("more than 80 LVR", "lvr_80-85%", "natural-language 'more than' bumps up"),
    ("no more than 80 LVR", "lvr_70-80%", "'no more than' is an upper bound"),
    ("at least 90 LVR", "lvr_90-95%", "'at least' is a lower bound"),
    ("Basic Home Loan", "", "no LVR signal -> blank"),
    ("Bridging Loan 6 months", "", "number but no LVR signal -> blank"),
]


def main() -> int:
    failures: list[str] = []
    for text, expected, why in NAMED_CASES:
        got = named_lvr_tier(text)
        if got != expected:
            failures.append(f"{why}: named_lvr_tier({text!r}) = {got!r}, expected {expected!r}")

    # End-to-end: resolve_lvr_tier must lift the Cairns name out of 'lvr_unspecified'.
    tier, source = resolve_lvr_tier("CLASSIC HOME LOAN VARIABLE <60 LVR IO", {}, [])
    if tier != "lvr_=60%":
        failures.append(f"resolve_lvr_tier Cairns <60: got {tier!r}/{source!r}, expected lvr_=60%")

    # A genuinely LVR-free product must remain unspecified (don't invent a tier).
    tier2, _ = resolve_lvr_tier("Bridging Loan", {}, [])
    if tier2 != "lvr_unspecified":
        failures.append(f"LVR-free product should stay unspecified, got {tier2!r}")

    if failures:
        print("FAIL verify_lvr_parsing:")
        for line in failures:
            print("  -", line)
        return 1
    print(f"PASS verify_lvr_parsing: {len(NAMED_CASES)} named cases + 2 e2e")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
