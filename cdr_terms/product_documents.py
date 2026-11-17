"""Conservative public document descriptors and official discovery seeds.

Specificity is a navigational classification, not legal applicability. Only a
retained independent clause/applicability review can promote candidate evidence.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit, urlunsplit

from .discovery import discover_references, document_url

POLICY = "product-document-discovery-2"
_COLLECTION = re.compile(r"/(?:terms(?:andconditions)?|terms-and-conditions|disclosure-documents|product-tcs|legal|documents)/?$", re.I)
_TYPES = (("pds", "pds"), ("product disclosure", "pds"), ("supplement", "supplement"),
          ("product schedule", "product-schedule"), ("fee schedule", "fee-schedule"), ("fees", "fee-schedule"),
          ("pricing", "fee-schedule"), ("rates", "rate-schedule"),
          ("eligibility", "eligibility"), ("terms", "terms-and-conditions"),
          ("conditions", "terms-and-conditions"), ("booklet", "terms-and-conditions"))
# Exact provider/product adapter. These are current discovery candidates, never
# assertions that today's document governed a historical product observation.
_ADAPTERS = ({"provider": "up", "name": "up home loan",
              "urls": ("https://up.com.au/home-loans/home-loan-booklet/", "https://up.com.au/docs/Up-Home-Loan-Booklet.pdf"),
              "evidence": "https://up.com.au/home-loans/home-loan-booklet/", "reviewedAt": "2026-11-18"},)


def _inner(record):
    value = record.get("data", record) if isinstance(record, dict) else {}
    return value if isinstance(value, dict) else {}


def _name(record):
    value = _inner(record)
    return str(value.get("name") or value.get("productName") or "").strip()


def _tokens(value):
    return re.findall(r"[a-z0-9]+", value.casefold())


def document_type(url, relation="", label=""):
    path = re.sub(r"([a-z])([A-Z])", r"\1 \2", unquote(urlsplit(url).path))
    text = " ".join((path.replace("-", " ").replace("_", " "), relation, label)).casefold()
    for token, kind in _TYPES:
        if token in text:
            return kind
    return "product-page" if relation == "overview" else "supporting-document"


def is_navigation(url):
    parsed = urlsplit(url)
    path = unquote(parsed.path)
    return path in ("", "/") or bool(re.fullmatch(r"/(?:index\.html?|home|en|en-au)/?", path, re.I))


def describe_reference(reference, record, *, product_key):
    value = reference.as_dict() if hasattr(reference, "as_dict") else dict(reference)
    url = document_url(value.get("url"))
    if url is None:
        raise ValueError("Document descriptor requires a valid source URL")
    relation = value.get("relation", "supporting")
    label = value.get("label") or ""
    navigation = is_navigation(url) or bool(re.search(r"/(?:sitemap[^/]*\.xml|robots\.txt)$", urlsplit(url).path, re.I))
    collection = bool(_COLLECTION.search(urlsplit(url).path))
    general = bool(re.search(r"(?:general[ _-]+(?:terms|conditions)|privacy|disclaimer)", unquote(urlsplit(url).path), re.I))
    title_tokens = _tokens(_name(record))
    target = _tokens(unquote(urlsplit(url).path) + " " + label)
    name_match = len(title_tokens) >= 2 and all(token in target for token in title_tokens)
    category = str(_inner(record).get('productCategory') or '').upper()
    family_tokens = (('mortgage', 'home', 'loan') if 'MORTGAGE' in category or 'loan' in title_tokens
                     else ('deposit',) if 'TERM_DEPOSIT' in category
                     else ('saving', 'savings', 'account') if 'SAVINGS' in category else ())
    family_match = any(token in target for token in family_tokens)
    specificity = ("background" if navigation else "provider-general" if collection or general
                   else "exact-product" if name_match else "product-family" if family_match else "provider-general")
    result = {**value, "url": url, "productKey": product_key,
              "documentType": "navigation" if navigation or collection else document_type(url, relation, label),
              "specificity": specificity,
              "relevance": "supplementary" if navigation or collection else "candidate",
              "verification": "declared-reference", "checkedAt": None,
              "effectiveFrom": None, "effectiveTo": None,
              "citations": [{"sourcePath": value["sourcePath"]}] if value.get("sourcePath") else []}
    return result


def describe_references(record, *, product_key):
    return [describe_reference(ref, record, product_key=product_key) for ref in discover_references(record)]


def discovery_plan(record, *, provider=""):
    """A no-network obligation for every product; seeds are candidates only.

    Never infer an official web host from a provider name or CDR API hostname.
    Same-host sitemap guesses are acquisition tasks, not published documents.
    """
    references = discover_references(record)
    needs_fallback = not references or all(is_navigation(ref.url) or _COLLECTION.search(urlsplit(ref.url).path)
                                          for ref in references)
    seeds = {}
    if needs_fallback:
        sources = [(ref.url, ref.sourcePath) for ref in references]
        # An explicit source-supplied website can seed discovery even though it
        # is correctly excluded from documentary evidence. Never use links.self:
        # a CDR API hostname is not the bank's public product website.
        value = _inner(record)
        for field in ("websiteUri", "websiteUrl"):
            url = document_url(value.get(field))
            if url:
                sources.append((url, "/" + field))
        for source_url, source_path in sources:
            parsed = urlsplit(source_url)
            if parsed.scheme == "https" and parsed.port in (None, 443):
                url = urlunsplit(("https", parsed.netloc, "/sitemap.xml", "", ""))
                seeds[url] = {"url": url, "sourcePath": source_path, "relation": "discovery_navigation",
                              "seedKind": "declared-official-host-sitemap", "originUrl": source_url}
        for adapter in _ADAPTERS:
            if str(provider or value.get("brand") or "").casefold() == adapter["provider"] and _name(record).casefold() == adapter["name"]:
                for url in adapter["urls"]:
                    seeds[url] = {"url": url, "sourcePath": "/discovery/provider-adapter", "relation": "discovery_navigation",
                                  "seedKind": "reviewed-provider-adapter", "adapterEvidence": adapter["evidence"],
                                  "adapterReviewedAt": adapter["reviewedAt"]}
    if len(seeds) > 16:
        # No silently incomplete plan can be sealed as a complete obligation.
        raise ValueError("Product discovery seed budget exceeded")
    if needs_fallback and not seeds:
        from .provider_websites import DIRECTORY_URL
        seeds[DIRECTORY_URL] = {'url': DIRECTORY_URL, 'sourcePath': '/discovery/official-provider-directory',
                                'relation': 'discovery_navigation', 'seedKind': 'official-provider-directory'}
    return {"policy": POLICY, "status": "queued" if seeds else "declared-references" if references else "missing-official-source",
            "declaredReferences": len(references), "seeds": sorted(seeds.values(), key=lambda item: item["url"]),
            "legalCompleteness": "unknown", "networkCalled": False}


def describe_product_sources(record, product_key, provider=""):
    """Declared references plus labelled reviewed-adapter discovery candidates.

    Adapter locators are not raw CDR pointers and explicitly name that origin.
    Sitemap guesses remain private navigation tasks, not product source links.
    """
    result = describe_references(record, product_key=product_key)
    seen = {(item["url"], item.get("sourcePath")) for item in result}
    for seed in discovery_plan(record, provider=provider)["seeds"]:
        if seed["seedKind"] != "reviewed-provider-adapter" or (seed["url"], seed["sourcePath"]) in seen:
            continue
        descriptor = describe_reference(seed, record, product_key=product_key)
        descriptor["verification"] = "discovery-candidate"
        descriptor["origin"] = "reviewed-provider-adapter"
        result.append(descriptor)
    return result
