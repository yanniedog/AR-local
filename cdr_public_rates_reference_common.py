"""Reviewed, deterministic reference-rate extraction primitives."""
from __future__ import annotations

import io
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from cdr_terms.identity import digest


class AdapterUnresolved(ValueError):
    pass


def percent(value) -> str:
    text = str(value).strip()
    if not re.fullmatch(r"\d+(?:\.\d{1,24})?", text):
        raise AdapterUnresolved("invalid_explicit_percentage")
    try:
        number = Decimal(text)
    except InvalidOperation as error:
        raise AdapterUnresolved("invalid_explicit_percentage") from error
    if not number.is_finite() or not 0 <= number <= 100:
        raise AdapterUnresolved("invalid_explicit_percentage")
    return format(number, "f").rstrip("0").rstrip(".") if "." in text else text


def australian_date(value: str) -> str:
    for pattern in ("%d %B %Y", "%A, %d %B %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=ZoneInfo("Australia/Sydney")).isoformat()
        except ValueError:
            continue
    raise AdapterUnresolved("effective_date_unresolved")


def condition(field: str, value: str, evidence_id: str) -> dict:
    return {"conditionId": "condition:public:" + digest([field, value]), "field": field,
            "operator": "eq", "value": value, "evidenceIds": [evidence_id]}


def reference(context: dict, key: str, name: str, value, locator: dict,
              *, effective_from=None, effective_to=None, scope: dict | None = None) -> tuple[dict, dict]:
    scope = scope or {}
    # A reference family survives source URL changes and additional captures.
    # Conflicting observations for that same family must not become new rates.
    identity = digest([context["providerId"], key, scope])
    evidence_id = "evidence:public:" + digest([context["sourceSha256"], locator])
    rate = {"referenceId": "reference:v1:" + identity, "componentId": "component:reference:" + identity,
            "name": name, "providerId": context["providerId"], "role": "reference",
            "unit": "percentage_points", "scopeId": "scope:reference:" + identity,
            "conditions": [condition(field, item, evidence_id) for field, item in scope.items()],
            "evidenceIds": [evidence_id], "source": {"rawType": "PUBLIC_REFERENCE_RATE", "rawValue": str(value),
            "pointer": locator.get("pointer", "")},
            "freshness": {"state": "unknown", "reasonCodes": ["check_binding_required"]}}
    if value not in (None, ""):
        rate["value"] = percent(value)
    else:
        rate["reasonCodes"] = ["public_reference_unavailable"]
    if effective_from:
        rate["effectiveFrom"] = effective_from
    if effective_to:
        rate["effectiveTo"] = effective_to
    evidence = {"evidenceId": evidence_id, "url": context["sourceUrl"],
                "sha256": context["sourceSha256"], "checkedAt": context["checkedAt"],
                "extractionVersion": context["adapterVersion"], "locator": json.dumps(locator, sort_keys=True, ensure_ascii=False)}
    return rate, evidence


def pdf_pages(body: bytes) -> list[str]:
    if len(body) > 16 * 1024**2 or not body.startswith(b"%PDF-"):
        raise AdapterUnresolved("invalid_pdf")
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(body))
        # Some publicly downloadable PDFs have an empty user password and copy
        # permissions. No authenticated document or nonempty password is used.
        if (reader.is_encrypted and not reader.decrypt("")) or len(reader.pages) != 4:
            raise AdapterUnresolved("pdf_structure_changed")
        texts = [page.extract_text() or "" for page in reader.pages]
    except AdapterUnresolved:
        raise
    except Exception as error:
        raise AdapterUnresolved("pdf_extraction_failed") from error
    if any(not text.strip() or len(text) > 100000 for text in texts):
        raise AdapterUnresolved("pdf_text_unavailable")
    return texts


class PublicHTML(HTMLParser):
    """Visible text plus retained table cells; scripts are never executed."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fragments, self.rows, self.mappings = [], [], []
        self.hidden = 0
        self.row = self.cell = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {"script", "style"}:
            self.hidden += 1
        if "productdata" in values.get("class", "").split():
            self.mappings.append({key: value for key, value in values.items() if key.startswith("data-")})
        if self.hidden:
            return
        if tag == "tr":
            self.row = []
        if tag in {"td", "th"} and self.row is not None:
            self.cell = ""
        if tag in {"p", "div", "tr", "br", "h1", "h2", "h3"}:
            self.fragments.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.fragments.append(data)
            if self.cell is not None:
                self.cell += data

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join(self.cell.split()))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def html(body: bytes) -> PublicHTML:
    if len(body) > 16 * 1024**2:
        raise AdapterUnresolved("document_too_large")
    try:
        parser = PublicHTML()
        parser.feed(body.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise AdapterUnresolved("html_extraction_failed") from error
    if not parser.fragments:
        raise AdapterUnresolved("empty_dynamic_table")
    return parser


def semantic_text(text: str) -> str:
    return " ".join(text.split())

