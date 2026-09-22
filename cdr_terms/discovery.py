"""Discover source references before the lossy display cleaner runs.

CDR reference paths are applicability evidence, not proof that every clause at
that URL applies to the product. In particular a product effectiveFrom never
becomes the document's effective date, nor a URL deletion a term withdrawal.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterator, Mapping
from urllib.parse import urlsplit, urlunsplit

_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_LEADING_ENCODED_SPACE = re.compile(r"^(?:%20)+(?=https?://)", re.I)
_SKIP = {"links", "meta", "cardArt"}
_NON_DOCUMENT = {"applicationuri", "imageuri", "logouri", "websiteuri"}
_RELATIONS = {
    "overview": "overview", "terms": "terms", "eligibility": "eligibility",
    "fees": "fees", "bundle": "bundle", "pds": "pds",
}


@dataclass(frozen=True)
class SourceReference:
    url: str
    sourcePath: str
    relation: str
    label: str | None = None
    # Retain anchors for locating clauses; fetch identity excludes the fragment.
    sourceUrl: str | None = None
    sourceNormalization: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


def document_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 8192:
        return None
    raw = value.strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or any(ord(c) < 32 for c in raw)):
        return None
    host = parsed.hostname.lower()
    if ":" in host:
        host = "[" + host + "]"
    default = 443 if parsed.scheme.lower() == "https" else 80
    netloc = host + (":" + str(port) if port and port != default else "")
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def _pointer(path: str, key: Any) -> str:
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


def reference_source_url(value: Any, normalization: str | None = None) -> str | None:
    """Verify a named correction without decoding path, query or credentials."""
    if normalization is None:
        return document_url(value)
    if (normalization != 'leading-encoded-space-v1'
            or not isinstance(value, str) or len(value) > 8192):
        return None
    candidate, count = _LEADING_ENCODED_SPACE.subn('', value.strip())
    return document_url(candidate) if count else None


def _relation(path: str) -> str:
    lowered = path.lower()
    for token, relation in _RELATIONS.items():
        if token in lowered:
            return relation
    return "supporting"


def _declared_reference(raw: str, path: str, relation: str, label=None) -> SourceReference | None:
    if len(raw) > 8192:
        return None
    # Some bank-declared URI fields encode a leading space before the scheme.
    # Decode no URL component; preserve the exact source and named correction.
    candidate, count = _LEADING_ENCODED_SPACE.subn('', raw.strip())
    url = document_url(candidate)
    if not url:
        return None
    return SourceReference(url, path, relation, str(label) if label else None, raw,
                           "leading-encoded-space-v1" if count else None)


def _walk(value: Any, path: str = "", reference_context: bool = False
          ) -> Iterator[SourceReference]:
    if isinstance(value, Mapping):
        label = value.get("description") or value.get("title") or value.get("name")
        for key, child in value.items():
            key_path = _pointer(path, key)
            lowered = str(key).lower()
            if key in _SKIP or lowered in _NON_DOCUMENT:
                continue
            uri_field = lowered.endswith(("uri", "uris"))
            contextual_uri = reference_context and lowered in {"url", "href"}
            if isinstance(child, str) and (uri_field or contextual_uri):
                reference = _declared_reference(child, key_path, _relation(key_path), label)
                if reference:
                    yield reference
            elif isinstance(child, str) and lowered in {"additionalinfo", "description"}:
                for match in _URL.finditer(child):
                    raw = match.group().rstrip(".,;)")
                    url = document_url(raw)
                    if url:
                        yield SourceReference(url, key_path, _relation(key_path),
                                              sourceUrl=raw)
            else:
                yield from _walk(child, key_path, reference_context or uri_field)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = _pointer(path, index)
            if reference_context and isinstance(child, str):
                reference = _declared_reference(child, child_path, _relation(path))
                if reference:
                    yield reference
            else:
                yield from _walk(child, child_path, reference_context)


def discover_references(record: Mapping[str, Any]) -> list[SourceReference]:
    """Inventory all declared nested references; preserve distinct scoped paths."""
    if isinstance(record.get("data"), Mapping):
        record = record["data"]
    references = { (ref.sourcePath, ref.url, ref.sourceUrl): ref for ref in _walk(record) }
    return sorted(references.values(), key=lambda ref: (ref.sourcePath, ref.url, ref.sourceUrl or ""))
