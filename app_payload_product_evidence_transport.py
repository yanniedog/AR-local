"""Prepare immutable lazy evidence assets offline; never authorize publication."""
from __future__ import annotations

import gzip
import io
import os
from pathlib import Path
import time

from cdr_atomic import _fsync_directory
from app_payload_product_evidence import bounded, read_page
from app_payload_product_evidence_contract import Limits, SCOPE, canonical, decode, digest, require, validate_manifest
from app_payload_product_evidence_transport_contract import (
    DeliveryLimits, SCHEMA, validate_binding, validate_capability, validate_index,
    validate_shard, wire_fact,
)


def compressed(raw):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", compresslevel=6, mtime=0) as stream:
        stream.write(raw)
    return output.getvalue()


def durable_create(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


class Packer:
    def __init__(self, output, binding, limits):
        self.output, self.binding, self.limits = output, binding, limits
        self.pending, self.routes, self.shards = [], [], []
        self.pending_bytes = 0
        self.raw_bytes, self.compressed_bytes = 0, 0
        self.deadline = time.monotonic() + 600

    def check(self):
        require(time.monotonic() < self.deadline, "delivery preparation deadline exceeded")

    def envelope(self, pages):
        return dict(schema=SCHEMA, binding=self.binding, pages=pages)

    def asset(self, kind, raw, blob=None):
        self.check()
        require(len(raw) <= getattr(self.limits, kind + "_raw_bytes"), "decoded delivery asset exceeds budget")
        blob = compressed(raw) if blob is None else blob
        require(len(blob) <= getattr(self.limits, kind + "_compressed_bytes"), "compressed delivery asset exceeds budget")
        self.raw_bytes += len(raw)
        self.compressed_bytes += len(blob)
        require(self.raw_bytes <= self.limits.raw_bytes and self.compressed_bytes <= self.limits.compressed_bytes,
                "aggregate delivery budget exceeded")
        sha = digest(blob)
        name = f"product-evidence-{kind}-{sha}.json.gz"
        durable_create(self.output / name, blob)
        return dict(name=name, sha256=sha, bytes=len(blob), decoded_bytes=len(raw))

    def flush(self):
        if not self.pending:
            return
        self.flush_group(self.pending, self.routes)
        self.pending, self.routes, self.pending_bytes = [], [], 0

    def flush_group(self, pages, routes):
        self.check()
        value = self.envelope(pages)
        raw = canonical(value)
        blob = compressed(raw)
        if len(blob) > self.limits.shard_compressed_bytes:
            require(len(pages) > 1, "single evidence page exceeds compressed delivery budget")
            middle = len(pages) // 2
            self.flush_group(pages[:middle], routes[:middle])
            self.flush_group(pages[middle:], routes[middle:])
            return
        require(len(self.shards) < self.limits.shards, "delivery shard count exceeded")
        validate_shard(value, {"binding": self.binding})
        descriptor = self.asset("shard", raw, blob)
        self.shards.append(descriptor)
        for position, (route, page) in enumerate(zip(routes, pages)):
            route["pages"].append(dict(shard=descriptor["sha256"], page=position, facts=len(page["facts"])))

    def append(self, route, page):
        self.check()
        page_bytes = len(canonical(page))
        envelope_bytes = len(canonical(self.envelope([])))
        if self.pending and envelope_bytes + self.pending_bytes + page_bytes + len(self.pending) > self.limits.shard_raw_bytes:
            self.flush()
        require(envelope_bytes + page_bytes <= self.limits.shard_raw_bytes, "single evidence page exceeds delivery budget")
        self.pending.append(page)
        self.routes.append(route)
        self.pending_bytes += page_bytes


def pack_snapshot(snapshot_root, output, *, expected_source, core_sha256, details_sha256, limits=DeliveryLimits()):
    """Produce an unpublished candidate. expected_source is binding, not selection authority."""
    limits.validate()
    root, output = Path(snapshot_root).absolute(), Path(output).absolute()
    require(not any(p.is_symlink() for p in (root, *root.parents, output, *output.parents)), "symlink delivery path")
    root, output = root.resolve(strict=True), output.resolve()
    require(not output.exists() and root != output and root not in output.parents
            and output not in root.parents, "delivery output must be new and separate")
    original = bounded(root / "snapshot.json", Limits().index_bytes)
    manifest = decode(original)
    validate_manifest(manifest)
    require(manifest["source"] == expected_source, "snapshot source differs from requested generation")
    binding = dict(source=manifest["source"], snapshot_sha256=digest(original),
                   core_sha256=core_sha256, details_sha256=details_sha256, scope=SCOPE)
    validate_binding(binding)
    output.mkdir(parents=True, exist_ok=False)
    writer, products = Packer(output, binding, limits), []
    for product in manifest["products"]:
        route = dict(identity=product["identity"], facts=product["facts"], pages=[])
        ids = set()
        for sequence, descriptor in enumerate(product["pages"]):
            facts = read_page(root, manifest, product, descriptor, sequence)
            for fact in facts:
                require(fact["fact_id"] not in ids, "duplicate fact across snapshot pages")
                ids.add(fact["fact_id"])
            writer.append(route, dict(identity=product["identity"], sequence=sequence,
                                      facts=[wire_fact(fact) for fact in facts]))
        require(len(ids) == product["facts"], "snapshot product count mismatch")
        products.append(route)
    writer.flush()
    index = dict(schema=SCHEMA, binding=binding, products=products)
    capability = dict(schema=SCHEMA, binding=binding, index=writer.asset("index", canonical(index)),
                      shards=writer.shards, products=len(products), facts=sum(p["facts"] for p in products))
    validate_capability(capability, limits=limits)
    validate_index(index, capability, limits=limits)
    from app_payload_product_evidence_delivery_check import verify_assets
    verify_assets(output, capability, limits=limits, deadline=writer.deadline)
    require(bounded(root / "snapshot.json", Limits().index_bytes) == original, "snapshot changed during packing")
    writer.check()
    prepared = dict(publication_authorized=False, selection_verified=False, capability=capability)
    temporary = output / "prepared.pending"
    durable_create(temporary, canonical(prepared) + b"\n")
    _fsync_directory(output)
    os.link(temporary, output / "prepared.json")
    _fsync_directory(output)
    temporary.unlink()
    _fsync_directory(output)
    return prepared
