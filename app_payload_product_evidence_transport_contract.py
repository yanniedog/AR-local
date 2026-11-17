"""Independent limits for a prepared, lazy descriptive-evidence delivery lane."""
from dataclasses import dataclass
import math

from app_payload_product_evidence_contract import (
    FACT_TEXT, IDENTITY, SHA, SCOPE, canonical, decode, fields, identity, require,
    validate_fact, validate_source,
)

SCHEMA = "ar-product-evidence-delivery-v1"
JSON_FIELDS = ("value", "source_value", "qualifiers", "min_value", "max_value")


def bounded_json(value):
    require(len(canonical(value)) <= 512 * 1024, "descriptive JSON exceeds byte budget")
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop(); nodes += 1
        require(depth <= 64 and nodes <= 65536, "descriptive JSON structure exceeds budget")
        if type(item) in (int, float):
            try: finite = math.isfinite(item)
            except OverflowError: finite = False
            require(finite, "nonfinite descriptive JSON")
        if isinstance(item, dict): pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list): pending.extend((child, depth + 1) for child in item)


@dataclass(frozen=True)
class DeliveryLimits:
    namespace_bytes: int = 64 * 1024
    index_raw_bytes: int = 4 * 1024**2
    index_compressed_bytes: int = 1024**2
    shard_raw_bytes: int = 4 * 1024**2
    shard_compressed_bytes: int = 1024**2
    raw_bytes: int = 1024**3
    compressed_bytes: int = 128 * 1024**2
    shards: int = 256
    product_raw_bytes: int = 64 * 1024**2
    product_compressed_bytes: int = 16 * 1024**2

    def validate(self):
        for key, value in self.__dict__.items():
            require(type(value) is int and 0 < value <= getattr(DeliveryLimits(), key), "invalid delivery budget")


def wire_fact(value):
    validate_fact(value)
    for key in JSON_FIELDS: bounded_json(value[key])
    return {**{key: value[key] for key in FACT_TEXT},
            **{key + "_json": canonical(value[key]).decode("utf-8") for key in JSON_FIELDS}}


def validate_wire_fact(value):
    fields(value, (*FACT_TEXT, *(key + "_json" for key in JSON_FIELDS)))
    require(all(type(value[key + "_json"]) is str for key in JSON_FIELDS), "evidence JSON text required")
    original = {**{key: value[key] for key in FACT_TEXT},
                **{key: decode(value[key + "_json"]) for key in JSON_FIELDS}}
    for key in JSON_FIELDS: bounded_json(original[key])
    validate_fact(original)


def validate_binding(value):
    fields(value, ("source", "snapshot_sha256", "core_sha256", "details_sha256", "scope"))
    validate_source(value["source"])
    for key in ("snapshot_sha256", "core_sha256", "details_sha256"):
        require(type(value[key]) is str and SHA.fullmatch(value[key]), "invalid delivery binding digest")
    require(value["scope"] == SCOPE, "unverified raw evidence scope")


def descriptor(value, kind, limits):
    fields(value, ("name", "sha256", "bytes", "decoded_bytes"))
    require(type(value["sha256"]) is str and SHA.fullmatch(value["sha256"]), "invalid asset digest")
    require(value["name"] == f"product-evidence-{kind}-{value['sha256']}.json.gz", "invalid asset name")
    for key, maximum in (("bytes", getattr(limits, kind + "_compressed_bytes")),
                         ("decoded_bytes", getattr(limits, kind + "_raw_bytes"))):
        require(type(value[key]) is int and 0 < value[key] <= maximum, "delivery asset exceeds budget")


def validate_capability(value, *, limits=DeliveryLimits()):
    limits.validate()
    fields(value, ("schema", "binding", "index", "shards", "products", "facts"))
    require(value["schema"] == SCHEMA, "unsupported evidence delivery schema")
    validate_binding(value["binding"])
    require(type(value["products"]) is int and 0 < value["products"] <= 20000, "invalid product count")
    require(type(value["facts"]) is int and 0 < value["facts"] <= 3000000, "invalid fact count")
    descriptor(value["index"], "index", limits)
    require(type(value["shards"]) is list and 0 < len(value["shards"]) <= limits.shards, "invalid shard count")
    names = set()
    for item in value["shards"]:
        descriptor(item, "shard", limits)
        require(item["name"] not in names, "duplicate shard")
        names.add(item["name"])
    assets = [value["index"], *value["shards"]]
    require(sum(row["bytes"] for row in assets) <= limits.compressed_bytes
            and sum(row["decoded_bytes"] for row in assets) <= limits.raw_bytes, "aggregate delivery budget exceeded")
    require(len(canonical(value)) <= limits.namespace_bytes, "namespace metadata budget exceeded")


def validate_index(value, capability, *, limits=DeliveryLimits()):
    fields(value, ("schema", "binding", "products"))
    require(value["schema"] == SCHEMA and value["binding"] == capability["binding"], "detached evidence index")
    require(type(value["products"]) is list and len(value["products"]) == capability["products"], "index product count mismatch")
    shards = {item["sha256"]: item for item in capability["shards"]}
    keys, positions, fact_count = set(), set(), 0
    for product in value["products"]:
        fields(product, ("identity", "facts", "pages"))
        fields(product["identity"], IDENTITY)
        key = identity(product["identity"])["product_key"]
        require(key not in keys, "duplicate product route")
        keys.add(key)
        require(type(product["facts"]) is int and 0 < product["facts"] <= 50000, "invalid routed fact count")
        require(type(product["pages"]) is list and 0 < len(product["pages"]) <= 20000, "invalid page routes")
        count, selected = 0, set()
        for page in product["pages"]:
            fields(page, ("shard", "page", "facts"))
            require(type(page["shard"]) is str and page["shard"] in shards, "undeclared evidence shard")
            require(type(page["page"]) is int and 0 <= page["page"] < 20000, "invalid page position")
            require(type(page["facts"]) is int and 0 < page["facts"] <= 1024, "invalid page count")
            position = page["shard"], page["page"]
            require(position not in positions, "duplicate evidence page route")
            positions.add(position)
            selected.add(page["shard"])
            count += page["facts"]
        require(count == product["facts"], "routed product count mismatch")
        require(sum(shards[sha]["decoded_bytes"] for sha in selected) <= limits.product_raw_bytes
                and sum(shards[sha]["bytes"] for sha in selected) <= limits.product_compressed_bytes,
                "product delivery exceeds cumulative budget")
        fact_count += count
    require(fact_count == capability["facts"], "routed total fact count mismatch")
    require({sha for sha, _ in positions} == set(shards), "unrouted evidence shard")
    require(len(canonical(value)) <= limits.index_raw_bytes, "routing index exceeds decoded budget")


def validate_shard(value, capability):
    fields(value, ("schema", "binding", "pages"))
    require(value["schema"] == SCHEMA and value["binding"] == capability["binding"], "detached evidence shard")
    require(type(value["pages"]) is list and 0 < len(value["pages"]) <= 20000, "invalid shard pages")
    for page in value["pages"]:
        fields(page, ("identity", "sequence", "facts"))
        fields(page["identity"], IDENTITY)
        identity(page["identity"])
        require(type(page["sequence"]) is int and page["sequence"] >= 0, "invalid product page sequence")
        require(type(page["facts"]) is list and 0 < len(page["facts"]) <= 1024, "invalid page facts")
        for fact in page["facts"]:
            validate_wire_fact(fact)
