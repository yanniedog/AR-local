"""Bounded sitemap navigation extraction; never product applicability proof."""
from __future__ import annotations

import io
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from .discovery import document_url

MAX_INPUT = 16 * 1024**2
MAX_LINKS = 256
MAX_ELEMENTS = 100000


def extract_sitemap(body, source_url):
    if len(body) > MAX_INPUT:
        return "", "failed", {"reason": "sitemap_input_byte_limit"}
    if b"\x00" in body:
        return "", "failed", {"reason": "unsupported_sitemap_encoding"}
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        return "", "failed", {"reason": "sitemap_entities_forbidden"}
    links, total, elements, root = [], 0, 0, None
    try:
        for event, element in ElementTree.iterparse(io.BytesIO(body), events=("start", "end")):
            tag = element.tag.rsplit("}", 1)[-1]
            if event == "start":
                elements += 1
                if root is None:
                    root = tag
                    if root not in {"urlset", "sitemapindex"}:
                        return "", "failed", {"reason": "unsupported_xml_document"}
                if elements > MAX_ELEMENTS:
                    return "", "failed", {"reason": "sitemap_element_limit"}
            elif tag == "loc":
                raw = (element.text or "").strip()
                total += 1
                if len(links) < MAX_LINKS:
                    links.append({"url": document_url(raw), "sourceUrl": raw,
                                  "href": raw, "anchor_index": total,
                                  "label": unquote(urlsplit(raw).path)[-2000:],
                                  "relation": "official_sitemap_candidate"})
                element.clear()
    except (ElementTree.ParseError, ValueError):
        return "", "failed", {"reason": "invalid_sitemap_xml"}
    if root is None:
        return "", "failed", {"reason": "empty_sitemap"}
    return "\n".join(item["sourceUrl"] for item in links), "partial", {
        "policy_version": "sitemap-navigation-1",
        "reason": "sitemap_candidates_not_product_applicability", "candidate_links": links,
        "candidate_links_total": total, "candidate_links_omitted": total - len(links),
        "sitemap_type": root, "legal_completeness": "unknown"}
