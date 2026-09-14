"""Conservative extraction: original bytes remain authoritative and private."""
from __future__ import annotations

import io
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from .discovery import document_url
from .identity import utc_now
from .store import EvidenceStore

EXTRACTOR_VERSION = "document-text-1"


class _HTMLText(HTMLParser):
    def __init__(self, source_url: str):
        super().__init__(convert_charrefs=True)
        self.source_url = source_url
        self.fragments: list[str] = []
        self.links: list[dict[str, str]] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        if self.hidden:
            return
        if tag in {"p", "div", "section", "tr", "br", "li", "h1", "h2", "h3", "table"}:
            self.fragments.append("\n")
        if tag in {"td", "th"}:
            self.fragments.append("\t")
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            url = document_url(urljoin(self.source_url, values["href"]))
            if url:
                self.links.append({"url": url, "sourceUrl": urljoin(self.source_url, values["href"]),
                                   "relation": "candidate_incorporated_reference"})

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        elif not self.hidden and tag in {"p", "div", "tr", "li", "table"}:
            self.fragments.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.fragments.append(data)


def extract_document(body: bytes, media_type: str, source_url: str) -> tuple[str, str, dict[str, Any]]:
    """Return text, completeness status and evidence; never claim semantics."""
    mime = media_type.split(";", 1)[0].strip().lower()
    if body.startswith(b"%PDF-") or mime == "application/pdf":
        return _extract_pdf(body)
    if mime in {"text/html", "application/xhtml+xml"}:
        charset_match = re.search(r"charset=([^;\s]+)", media_type, re.I)
        charset = charset_match.group(1).strip("\"'") if charset_match else "utf-8"
        try:
            decoded = body.decode(charset)
        except (LookupError, UnicodeDecodeError):
            return "", "failed", {"reason": "unverified_html_encoding"}
        parser = _HTMLText(source_url)
        parser.feed(decoded)
        parser.close()
        return "".join(parser.fragments), "partial", {
            "reason": "html_layout_dynamic_content_and_incorporated_links_unreviewed",
            "candidate_links": [json.loads(link) for link in sorted({json.dumps(link, sort_keys=True) for link in parser.links})],
        }
    if mime in {"text/plain", "application/json"}:
        try:
            text = body.decode("utf-8-sig")
            if mime == "application/json":
                json.loads(text)
        except (UnicodeDecodeError, ValueError):
            return "", "failed", {"reason": "invalid_text_encoding_or_json"}
        return text, "complete" if text else "failed", {"characters": len(text)}
    return "", "failed", {"reason": "unsupported_document_type"}


def _extract_pdf(body: bytes) -> tuple[str, str, dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", "failed", {"reason": "pdf_extractor_unavailable"}
    try:
        reader = PdfReader(io.BytesIO(body))
        if reader.is_encrypted:
            return "", "failed", {"reason": "encrypted_pdf"}
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception:
        return "", "failed", {"reason": "pdf_extraction_failed"}
    unreadable = [index + 1 for index, page in enumerate(pages) if not page.strip()]
    return "\n\f\n".join(pages), "partial", {
        "pages": len(pages), "unreadable_pages": unreadable,
        "reason": "pdf_tables_footnotes_layout_and_ocr_require_review",
    }


def extract_version(store: EvidenceStore, version_id: str) -> str:
    row = store.db.execute("SELECT v.*, d.source_url FROM document_versions v "
                           "JOIN documents d USING(document_id) WHERE document_version_id=?", (version_id,)).fetchone()
    if not row:
        raise ValueError("Extraction requires a retained document version")
    text, status, coverage = extract_document(store.read_blob(row["content_sha256"]),
                                              row["media_type"], row["source_url"])
    return store.register_extraction(document_version_id=version_id, extractor_version=EXTRACTOR_VERSION,
                                     text=text, observed_at=utc_now(), status=status, coverage=coverage)
