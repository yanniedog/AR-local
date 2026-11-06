"""NAB indicator and CommBank reference PDF adapters, validated by public captures."""
from __future__ import annotations

import re

from cdr_terms.identity import digest
from cdr_public_rates_reference_common import (
    AdapterUnresolved, australian_date, pdf_pages, reference, semantic_text,
)


def _date(text: str, prefix: str) -> str:
    found = re.findall(prefix + r"(\d{1,2} [A-Za-z]+ \d{4})", text)
    if len(set(found)) != 1:
        raise AdapterUnresolved("effective_date_unresolved")
    return australian_date(found[0])


def _structure(pages: list[str], *, cba=False) -> str:
    normalized = []
    for page in pages:
        for line in page.splitlines():
            line = semantic_text(line)
            line = re.sub(r"Effective (?:as at )?\d{1,2} [A-Za-z]+ \d{4}\.?$", "Effective $DATE", line)
            if cba:
                line = re.sub(r"(Page \d of 4 002-842) \d{6}$", r"\1 $EDITION", line)
                if re.match(r"LVR \d", line):
                    bound = re.match(r"LVR [\d.% ]+(?:or below|to [\d.%]+)", line)
                    if not bound:
                        raise AdapterUnresolved("lvr_structure_changed")
                    line = bound.group() + re.sub(r"\d+\.\d+%", "$RATE", line[bound.end():])
                elif line.startswith("Reference Rate p.a.") or re.search(r" \d+\.\d+% \d+\.\d+% \d+\.\d+% \d+\.\d+%$", line):
                    line = re.sub(r"\d+\.\d+%", "$RATE", line)
            else:
                line = re.sub(r" \d+\.\d+%$", " $RATE", line)
            normalized.append(line)
    return digest(normalized)


def nab(body: bytes, context: dict) -> dict:
    pages = pdf_pages(body)
    if "Explanation of Indicator rates" not in pages[3] or "Indicator Rate %pa" not in pages[0]:
        raise AdapterUnresolved("reference_definition_changed")
    rates, evidence = [], []
    effective = _date("\n".join(pages), r"Effective ")
    for page, text in enumerate(pages, 1):
        scope = {"purpose": "INVESTMENT"} if page == 2 else {"purpose": "OWNER_OCCUPIED"} if page == 1 else {}
        if page == 3:
            scope["customerCategory"] = "OVERSEAS_BORROWER"
        if page == 4:
            scope["customerCategory"] = "SMSF"
        for line_number, line in enumerate(text.splitlines(), 1):
            found = re.fullmatch(r"(.+?)\s+(\d+\.\d+)%", line.strip())
            if not found:
                continue
            name, value = found.groups()
            name = re.sub(r"^NAB (?:Tailored|Base|Flexi Plus|Portfolio Package) - [A-Za-z ]+? (?=(?:Variable|Base|FlexiPlus|NAB Portfolio))", "", name)
            item_scope = dict(scope)
            item_scope["repayment"] = "INTEREST_ONLY" if re.search(r"Interest [Oo]nly|Interest in Advance", name) else "PRINCIPAL_AND_INTEREST"
            term = re.match(r"(\d+) years? ", name)
            if term:
                item_scope["termMonths"] = str(int(term[1]) * 12)
                item_scope["package"] = "NAB_PACKAGE" if "Package Fixed" in name else "NONE"
            locator = {"page": page, "line": line_number, "text": line.strip()}
            rate, source = reference(context, semantic_text(name).casefold(), name, value, locator,
                                     effective_from=effective, scope=item_scope)
            rates.append(rate)
            evidence.append(source)
    if len(rates) != 106:
        raise AdapterUnresolved("indicator_row_inventory_changed")
    return {"referenceRates": rates, "evidence": evidence, "semanticSha256": _structure(pages)}


def cba(body: bytes, context: dict) -> dict:
    pages = pdf_pages(body)
    rates, evidence = [], []
    for page_number in (1, 3):
        text = pages[page_number - 1]
        effective = _date(text, r"Effective as at ")
        purpose = "OWNER_OCCUPIED" if page_number == 1 else "INVESTMENT"
        blocks = re.split(r"\n(?=Standard Variable Rate \(Complete\)|Simple Home Loan|Digi Home Loan)", text)
        matches = 0
        for block in blocks:
            found = re.search(r"Reference Rate p.a. (\d+\.\d+)% (\d+\.\d+)%", block)
            if not found:
                continue
            family = block.splitlines()[0].strip()
            if family not in {"Standard Variable Rate (Complete)", "Simple Home Loan", "Digi Home Loan"}:
                raise AdapterUnresolved("reference_heading_changed")
            for repayment, value in zip(("PRINCIPAL_AND_INTEREST", "INTEREST_ONLY"), found.groups()):
                key = f"{purpose}:{family}:{repayment}"
                name = f"{family} reference - {'owner occupied' if page_number == 1 else 'investment'} - {repayment.replace('_', ' ').lower()}"
                rate, source = reference(context, key, name, value,
                    {"page": page_number, "section": family, "text": found.group()},
                    effective_from=effective, scope={"purpose": purpose, "repayment": repayment})
                rates.append(rate)
                evidence.append(source)
            matches += 1
        if matches != 3:
            raise AdapterUnresolved("reference_table_inventory_changed")
    # Fixed tables explicitly distinguish reference from package/net rates.
    for page_number in (2, 4):
        text = pages[page_number - 1]
        effective = _date(text, r"Effective as at ")
        purpose = "OWNER_OCCUPIED" if page_number == 2 else "INVESTMENT"
        pending_term, found_rows = None, 0
        for line_number, line in enumerate(text.splitlines(), 1):
            term = re.fullmatch(r"([1-5]) Year", line.strip())
            if term:
                pending_term = int(term[1])
            found = re.search(r"(\d+\.\d+)% (\d+\.\d+)% (\d+\.\d+)% (\d+\.\d+)%$", line.strip())
            if not found:
                continue
            if pending_term is None:
                raise AdapterUnresolved("fixed_term_unresolved")
            repayment = "PRINCIPAL_AND_INTEREST" if "Principal and Interest" in line else "INTEREST_ONLY"
            scope = {"purpose": purpose, "repayment": repayment, "termMonths": str(pending_term * 12)}
            name = f"{pending_term} year fixed reference - {purpose.replace('_',' ').lower()} - {repayment.replace('_',' ').lower()}"
            rate, source = reference(context, name, name, found[3], {"page": page_number, "line": line_number, "text": line},
                                     effective_from=effective, scope=scope)
            rates.append(rate)
            evidence.append(source)
            found_rows += 1
        if found_rows != 10:
            raise AdapterUnresolved("fixed_reference_table_changed")
    return {"referenceRates": rates, "evidence": evidence, "semanticSha256": _structure(pages, cba=True)}
