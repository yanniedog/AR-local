"""Bounded, unpublished normalized-fact snapshots; never publication authority."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math
import re

from cdr_product_facts import NORMALIZATION_VERSION

SCHEMA = "ar-product-fact-snapshot-v1"
SCOPE = "normalized_facts_only; raw_null_empty_and_transport_envelope_not_inventoried"
SHA = re.compile(r"[0-9a-f]{64}")
COLUMNS = (
    "run_date", "dataset", "provider", "product_id", "product_key", "product_name",
    "fact_id", "kind", "canonical_key", "value_type", "value_boolean", "value_number",
    "value_text", "value_json", "min_value", "max_value", "unit", "mapping",
    "source_path", "source_pattern", "source_value_json", "qualifiers_json",
)
IDENTITY = ("dataset", "provider", "product_id", "product_key", "product_name")
FACT_TEXT = ("fact_id", "kind", "canonical_key", "value_type", "unit", "mapping", "source_path", "source_pattern")


@dataclass(frozen=True)
class Limits:
    database_bytes: int = 4 * 1024**3
    raw_bytes: int = 1024**3
    compressed_bytes: int = 256 * 1024**2
    page_raw_bytes: int = 512 * 1024
    page_compressed_bytes: int = 1024**2
    index_bytes: int = 8 * 1024**2
    page_rows: int = 1024
    products: int = 20000
    pages: int = 20000
    facts: int = 3000000
    product_facts: int = 50000
    seconds: int = 600

    def validate(self):
        for key, value in asdict(self).items():
            if type(value) is not int or not 0 < value <= getattr(Limits(), key):
                raise ValueError("invalid or increased evidence budget: " + key)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate evidence JSON field")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("nonfinite evidence JSON")

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    canonical(value)  # Also rejects finite-looking literals that overflow to inf.
    return value


def fields(value, names):
    require(type(value) is dict and set(value) == set(names), "unexpected evidence fields")


def identity(row):
    result = {key: row[key] for key in IDENTITY}
    require(all(type(value) is str and value for value in result.values()), "missing product identity")
    return result


def fact(row):
    value = decode(row["value_json"])
    expected = (value if type(value) is bool else None,
                value if type(value) in (float, int) else None,
                value if type(value) is str else None)
    boolean = row["value_boolean"]
    require(boolean is None or type(boolean) is int and boolean in (0, 1), "invalid stored boolean")
    actual = (None if boolean is None else bool(boolean), row["value_number"], row["value_text"])
    require(actual == expected, "stored value contradicts typed columns")
    result = {key: row[key] for key in FACT_TEXT}
    result.update(value=value, source_value=decode(row["source_value_json"]),
                  qualifiers=decode(row["qualifiers_json"]),
                  min_value=row["min_value"], max_value=row["max_value"])
    validate_fact(result)
    return result


def validate_fact(value):
    fields(value, (*FACT_TEXT, "value", "source_value", "qualifiers", "min_value", "max_value"))
    require(all(type(value[key]) is str and value[key] for key in FACT_TEXT), "missing fact identity/provenance")
    require(type(value["qualifiers"]) is dict, "fact qualifiers must be an object")
    require(value["mapping"] in {"canonical", "canonical_text", "preserved"}, "unknown fact mapping")
    kind, raw = value["value_type"], value["value"]
    valid = ((kind == "boolean" and type(raw) is bool)
             or (kind in {"number", "rate", "money"} and type(raw) in (int, float) and math.isfinite(raw))
             or (kind in {"text", "duration", "enum"} and type(raw) is str)
             or (kind == "range" and raw is None))
    require(valid, "unsupported or contradictory normalized value type")
    for key in ("min_value", "max_value"):
        bound = value[key]
        require(bound is None or type(bound) in (int, float) and math.isfinite(bound), "invalid numeric bound")
    has_bound = value["min_value"] is not None or value["max_value"] is not None
    require(has_bound == (kind == "range"), "range requires a bound; scalar facts cannot have range bounds")
    canonical(value)


def validate_source(value):
    fields(value, ("generation_id", "observation_date", "observation_state", "contract_digest", "source_generation_digest",
                   "contract_file_sha256", "contract_normalization", "fact_normalization", "database"))
    require(date.fromisoformat(value["observation_date"]).isoformat() == value["observation_date"], "invalid date")
    require(value["observation_state"] in {"complete", "partial", "failed"}, "invalid source observation state")
    require(type(value["generation_id"]) is str and re.fullmatch(
        r"obs-" + re.escape(value["observation_date"]) + r"-[0-9a-f]{16}", value["generation_id"]),
        "invalid generation identity/date")
    for key in ("contract_digest", "source_generation_digest", "contract_file_sha256"):
        require(type(value[key]) is str and SHA.fullmatch(value[key]), "invalid source digest")
    require(type(value["contract_normalization"]) is str and value["contract_normalization"], "missing contract normalization")
    require(value["fact_normalization"] == NORMALIZATION_VERSION, "unsupported fact normalization")
    fields(value["database"], ("path", "sha256", "bytes"))
    require(value["database"]["path"] == "local-cdr.sqlite", "wrong database artifact")
    require(type(value["database"]["sha256"]) is str and SHA.fullmatch(value["database"]["sha256"]), "invalid database digest")
    require(type(value["database"]["bytes"]) is int and 0 < value["database"]["bytes"] <= Limits().database_bytes, "invalid database size")


def validate_page(value, source, product, sequence):
    fields(value, ("schema", "source", "product", "sequence", "facts"))
    require(value["schema"] == SCHEMA and value["source"] == source and value["product"] == product
            and type(value["sequence"]) is int and value["sequence"] == sequence, "detached evidence page")
    require(type(value["facts"]) is list and 0 < len(value["facts"]) <= Limits().page_rows, "invalid page fact count")
    for item in value["facts"]:
        validate_fact(item)


def validate_manifest(value):
    fields(value, ("schema", "source", "scope", "publication_authorized", "selection_verified",
                   "coverage", "products", "totals"))
    require(value["schema"] == SCHEMA and value["scope"] == SCOPE, "wrong snapshot schema/scope")
    require(value["publication_authorized"] is False and value["selection_verified"] is False,
            "offline evidence cannot assert publication/selection authority")
    require(value["coverage"] == "complete_for_bound_fact_table_only", "invalid evidence coverage claim")
    validate_source(value["source"])
    require(type(value["products"]) is list and 0 < len(value["products"]) <= Limits().products, "invalid product count")
    keys, names = set(), set()
    counts = dict(products=len(value["products"]), facts=0, pages=0, raw_bytes=0, compressed_bytes=0)
    for product in value["products"]:
        fields(product, ("identity", "facts", "pages"))
        fields(product["identity"], IDENTITY)
        key = identity(product["identity"])["product_key"]
        require(key not in keys, "duplicate product route")
        keys.add(key)
        require(type(product["facts"]) is int and 0 < product["facts"] <= Limits().product_facts, "invalid product facts")
        require(type(product["pages"]) is list and product["pages"], "missing product pages")
        count = 0
        for page in product["pages"]:
            fields(page, ("name", "sha256", "bytes", "raw_bytes", "facts"))
            require(type(page["sha256"]) is str and SHA.fullmatch(page["sha256"]), "invalid page digest")
            require(page["name"] == "facts-" + page["sha256"] + ".json.gz" and page["name"] not in names, "invalid/duplicate page name")
            names.add(page["name"])
            for field, limit in (("bytes", Limits().page_compressed_bytes), ("raw_bytes", Limits().page_raw_bytes), ("facts", Limits().page_rows)):
                require(type(page[field]) is int and 0 < page[field] <= limit, "invalid page budget/count")
            counts["pages"] += 1
            counts["raw_bytes"] += page["raw_bytes"]
            counts["compressed_bytes"] += page["bytes"]
            count += page["facts"]
        require(count == product["facts"], "product count mismatch")
        counts["facts"] += count
    require(value["totals"] == counts and all(type(n) is int for n in value["totals"].values()), "snapshot totals mismatch")
    for field, count in counts.items():
        require(count <= getattr(Limits(), field), "snapshot exceeds aggregate budget")
    require(len(canonical(value)) <= Limits().index_bytes, "snapshot index exceeds budget")
