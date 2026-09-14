"""Conservative extraction: original bytes remain authoritative and private."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from .discovery import document_url
from .identity import utc_now
from .pdf_extraction import extract_pdf
from .store import EvidenceStore

EXTRACTOR_VERSION = "document-text-3"
MAX_HTML_LINKS = 256


class _HTMLText(HTMLParser):
    def __init__(self, source_url: str):
        super().__init__(convert_charrefs=True)
        self.source_url = source_url
        self.fragments: list[str] = []
        self.links: list[dict[str, Any]] = []
        self.link_count = 0
        self.active_link: dict[str, Any] | None = None
        self.base_href_present = False
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
        if tag == "base" and values.get("href"):
            self.base_href_present = True
        if tag == "a" and values.get("href"):
            self.link_count += 1
            self.active_link = None
            if len(self.links) < MAX_HTML_LINKS:
                href = values["href"]
                try:
                    source = urljoin(self.source_url, href)
                except ValueError:
                    source = href
                self.active_link = {"url": document_url(source), "sourceUrl": source,
                                    "href": href, "anchor_index": self.link_count,
                                    "line": self.getpos()[0], "column": self.getpos()[1],
                                    "label": "", "rel": values.get("rel", ""),
                                    "relation": "candidate_incorporated_reference"}
                self.links.append(self.active_link)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.active_link = None
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        elif not self.hidden and tag in {"p", "div", "tr", "li", "table"}:
            self.fragments.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.fragments.append(data)
            if self.active_link is not None:
                self.active_link["label"] = (self.active_link["label"] + data)[:2000]


def extract_document(body: bytes, media_type: str, source_url: str) -> tuple[str, str, dict[str, Any]]:
    """Return text, completeness status and evidence; never claim semantics."""
    mime = media_type.split(";", 1)[0].strip().lower()
    if body.startswith(b"%PDF-") or mime == "application/pdf":
        return extract_pdf(body, source_url)
    if mime in {"text/html", "application/xhtml+xml"}:
        charset_match = re.search(r"charset=([^;\s]+)", media_type, re.I)
        charset = charset_match.group(1).strip("\"'") if charset_match else "utf-8"
        try:
            decoded = body.decode(charset)
        except (LookupError, UnicodeDecodeError):
            return "", "failed", {"reason": "unverified_html_encoding"}
        parser = _HTMLText(source_url)
        try:
            parser.feed(decoded)
            parser.close()
        except (ValueError, AssertionError):
            return "", "failed", {"reason": "html_parse_failed"}
        return "".join(parser.fragments), "partial", {
            "reason": "html_layout_dynamic_content_and_incorporated_links_unreviewed",
            "candidate_links": parser.links,
            "candidate_links_total": parser.link_count,
            "candidate_links_omitted": parser.link_count - len(parser.links),
            "html_base_href_requires_review": parser.base_href_present,
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


def extract_version(store: EvidenceStore, version_id: str, *, check_id: str | None = None) -> str:
    row = store.db.execute("SELECT v.*, d.source_url FROM document_versions v "
                           "JOIN documents d USING(document_id) WHERE document_version_id=?", (version_id,)).fetchone()
    if not row:
        raise ValueError("Extraction requires a retained document version")
    check = store.db.execute("SELECT * FROM acquisition_checks WHERE document_version_id=? "
                             + ("AND check_id=? " if check_id else "")
                             + "ORDER BY checked_at DESC,sequence DESC LIMIT 1",
                             (version_id, check_id) if check_id else (version_id,)).fetchone()
    if check_id and not check:
        raise ValueError("Extraction check must bind its retained document version")
    metadata = json.loads(check["metadata_json"]) if check else {}
    final_url = document_url(metadata.get("final_url"))
    text, status, coverage = extract_document(store.read_blob(row["content_sha256"]),
                                              row["media_type"], final_url or row["source_url"])
    coverage["resolution_base_url"] = final_url or row["source_url"]
    coverage["resolution_base_verified"] = final_url is not None
    return store.register_extraction(document_version_id=version_id, extractor_version=EXTRACTOR_VERSION,
                                     text=text, observed_at=utc_now(), status=status, coverage=coverage)
