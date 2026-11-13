"""Offline source-bound fact pages. No network, selection, publication or ingest."""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import asdict
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import time

from cdr_export_contract import load_contract
from cdr_product_facts import NORMALIZATION_VERSION
from app_payload_product_evidence_contract import (
    COLUMNS, Limits, SCHEMA, SCOPE, canonical, decode, digest, fact, identity,
    require, validate_manifest, validate_page, validate_source,
)


def regular(path):
    path = Path(path).absolute()
    require(not any(part.is_symlink() for part in (path, *path.parents)), "symlink evidence path")
    require(path.is_file(), "missing regular evidence file")
    return path.resolve(strict=True)


def signature(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def bounded(path, limit):
    path = regular(path)
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    require(len(value) <= limit, "evidence file exceeds byte budget")
    return value


class Budget:
    def __init__(self, limits):
        limits.validate()
        self.limits = limits
        self.deadline = time.monotonic() + limits.seconds
        self.totals = dict(products=0, facts=0, pages=0, raw_bytes=0, compressed_bytes=0)

    def check(self):
        require(time.monotonic() < self.deadline, "evidence deadline exceeded")

    def charge(self, **counts):
        self.check()
        for key, value in counts.items():
            self.totals[key] += value
            require(self.totals[key] <= getattr(self.limits, key), "evidence aggregate budget exceeded: " + key)


def file_digest(path, budget):
    require(path.stat().st_size <= budget.limits.database_bytes, "database exceeds byte budget")
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            budget.check()
            value.update(chunk)
    return value.hexdigest()


def no_journals(database):
    for suffix in ("-wal", "-journal"):
        path = database.with_name(database.name + suffix)
        require(not path.is_symlink() and (not path.exists() or path.stat().st_size == 0),
                "nonempty or unsafe SQLite journal; supply verified committed database")


def source_binding(database, contract_path, budget):
    raw = bounded(contract_path, 16 * 1024**2)
    decode(raw)
    contract = load_contract(contract_path)
    require(bounded(contract_path, 16 * 1024**2) == raw, "source contract changed while loading")
    records = [row for row in contract["artifacts"] if row["path"] == "local-cdr.sqlite"]
    require(len(records) == 1, "one bound database artifact required")
    artifact = records[0]
    require(database.stat().st_size == artifact["bytes"] and file_digest(database, budget) == artifact["sha256"],
            "database differs from original export contract")
    result = {"generation_id": contract["generation_id"], "observation_date": contract["observation_date"],
              "observation_state": contract["observation_state"],
              "contract_digest": contract["contract_digest"], "source_generation_digest": contract["source_generation_digest"],
              "contract_file_sha256": digest(raw), "contract_normalization": contract["normalization_version"],
              "fact_normalization": NORMALIZATION_VERSION, "database": dict(artifact)}
    validate_source(result)
    return result


def open_database(path, source, budget):
    connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA cache_size=-2048")
        connection.execute("PRAGMA mmap_size=0")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, budget.limits.page_raw_bytes)
        connection.set_progress_handler(lambda: int(time.monotonic() >= budget.deadline), 10000)
        rows = connection.execute("SELECT key, value FROM schema_meta WHERE key IN ('version', 'normalization_version') LIMIT 3").fetchmany(3)
        meta = dict(rows)
        require(len(rows) == len(meta) == 2, "ambiguous database metadata")
        # Versions 8/9 share the exact fact columns; other exported tables differ.
        require(meta.get("version") in {"8", "9"} and meta.get("normalization_version") == NORMALIZATION_VERSION,
                "unsupported database schema or fact normalization")
        require({row[1] for row in connection.execute("PRAGMA table_info(bank_product_facts)")} == set(COLUMNS),
                "unsupported fact columns")
        index = connection.execute("PRAGMA index_info(idx_bank_product_facts_product)").fetchmany(4)
        require([row[2] for row in index] == ["run_date", "product_key", "kind"], "bounded product index required")
        require(connection.execute("SELECT 1 FROM bank_product_facts WHERE run_date != ? OR run_date IS NULL LIMIT 1",
                                   (source["observation_date"],)).fetchone() is None, "database contains another observation date")
        connection.row_factory = sqlite3.Row
        return connection
    except BaseException:
        connection.close()
        raise


def write_page(output, source, product, sequence, rows, budget):
    raw = canonical(dict(schema=SCHEMA, source=source, product=product, sequence=sequence, facts=rows))
    require(len(raw) <= budget.limits.page_raw_bytes, "single fact/page exceeds raw budget")
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", compresslevel=6, mtime=0) as stream:
        stream.write(raw)
    compressed = buffer.getvalue()
    require(len(compressed) <= budget.limits.page_compressed_bytes, "page exceeds compressed budget")
    budget.charge(pages=1, raw_bytes=len(raw), compressed_bytes=len(compressed))
    checksum = digest(compressed)
    name = "facts-" + checksum + ".json.gz"
    with (output / name).open("xb") as stream:
        stream.write(compressed)
    return dict(name=name, sha256=checksum, bytes=len(compressed), raw_bytes=len(raw), facts=len(rows))


def write_product(rows, output, source, budget, pending):
    product, pages, values, ids = identity(pending), [], [], set()
    envelope = len(canonical(dict(schema=SCHEMA, source=source, product=product, sequence=0, facts=[])))
    size, count = envelope, 0
    while pending is not None and pending["product_key"] == product["product_key"]:
        budget.check()
        require(identity(pending) == product, "conflicting identities for product route")
        item = fact(pending)
        require(item["fact_id"] not in ids, "duplicate fact identity")
        ids.add(item["fact_id"])
        count += 1
        require(count <= budget.limits.product_facts, "product fact count exceeds budget")
        budget.charge(facts=1)
        item_bytes = len(canonical(item)) + 1
        # Reserve sequence digit growth before append; never encode an unbounded list.
        if values and (len(values) >= budget.limits.page_rows or size + item_bytes + 12 > budget.limits.page_raw_bytes):
            pages.append(write_page(output, source, product, len(pages), values, budget))
            values, size = [], envelope
        require(size + item_bytes + 12 <= budget.limits.page_raw_bytes, "single fact exceeds page budget")
        values.append(item)
        size += item_bytes
        pending = next(rows, None)
    pages.append(write_page(output, source, product, len(pages), values, budget))
    return dict(identity=product, facts=count, pages=pages), pending


def prepare_snapshot(database, contract_path, output, *, limits=Limits()):
    """Create a NEW private snapshot; error leaves evidence but no completion marker."""
    budget = Budget(limits)
    database, contract_path = regular(database), regular(contract_path)
    output = Path(output).absolute()
    require(not any(part.is_symlink() for part in (output, *output.parents)), "symlink output path")
    output = output.resolve()
    require(not output.exists() and not output.is_relative_to(database.parent)
            and not database.is_relative_to(output) and not contract_path.is_relative_to(output)
            and not output.is_relative_to(contract_path.parent), "existing or overlapping snapshot destination")
    initial = signature(database), signature(contract_path)
    no_journals(database)
    source = source_binding(database, contract_path, budget)
    with closing(open_database(database, source, budget)) as connection:
        output.mkdir(parents=True, exist_ok=False)
        # Required existing index avoids a full-table in-memory sort/materialization.
        columns = ", ".join('"' + key + '"' for key in COLUMNS)
        rows = iter(connection.execute(f"SELECT {columns} FROM bank_product_facts INDEXED BY idx_bank_product_facts_product "
                                       "WHERE run_date=? ORDER BY product_key, kind", (source["observation_date"],)))
        pending, products = next(rows, None), []
        require(pending is not None, "empty fact snapshot")
        index_bytes = 0
        while pending is not None:
            budget.charge(products=1)
            product, pending = write_product(rows, output, source, budget, pending)
            index_bytes += len(canonical(product)) + 1
            require(index_bytes <= limits.index_bytes, "snapshot index exceeds budget")
            products.append(product)
    no_journals(database)
    require(initial == (signature(database), signature(contract_path)), "source changed during snapshot")
    require(file_digest(database, budget) == source["database"]["sha256"]
            and digest(bounded(contract_path, 16 * 1024**2)) == source["contract_file_sha256"], "source bytes changed during snapshot")
    require(initial == (signature(database), signature(contract_path)), "source changed during final verification")
    no_journals(database)
    manifest = dict(schema=SCHEMA, source=source, scope=SCOPE, publication_authorized=False,
                    selection_verified=False, coverage="complete_for_bound_fact_table_only",
                    products=products, totals=budget.totals)
    validate_manifest(manifest)
    encoded = canonical(manifest) + b"\n"
    require(len(encoded) <= limits.index_bytes, "snapshot index exceeds budget")
    budget.check()
    temporary = output / "snapshot.pending"
    with temporary.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, output / "snapshot.json")  # Atomic create-once completion marker.
    temporary.unlink()
    return manifest


def read_manifest(root):
    root = Path(root)
    value = decode(bounded(root / "snapshot.json", Limits().index_bytes))
    validate_manifest(value)
    return value


def read_page(root, manifest, product, descriptor, sequence):
    blob = bounded(Path(root) / descriptor["name"], descriptor["bytes"])
    require(len(blob) == descriptor["bytes"] and digest(blob) == descriptor["sha256"], "page bytes/hash mismatch")
    with gzip.GzipFile(fileobj=io.BytesIO(blob)) as stream:
        raw = stream.read(descriptor["raw_bytes"] + 1)
    require(len(raw) == descriptor["raw_bytes"], "page decoded bytes mismatch")
    value = decode(raw)
    validate_page(value, manifest["source"], product["identity"], sequence)
    require(len(value["facts"]) == descriptor["facts"], "page fact count mismatch")
    return value["facts"]


def iter_product_facts(root, product_key):
    """Validate metadata and only this product's bounded pages; not a publication read."""
    manifest = read_manifest(root)
    selected = next((row for row in manifest["products"] if row["identity"]["product_key"] == product_key), None)
    require(selected is not None, "product absent from snapshot; absence is not withdrawal")
    ids = set()
    for number, page in enumerate(selected["pages"]):
        for item in read_page(root, manifest, selected, page, number):
            require(item["fact_id"] not in ids, "duplicate fact across pages")
            ids.add(item["fact_id"])
            yield item


def validate_snapshot(root, *, limits=Limits()):
    budget = Budget(limits)
    manifest = read_manifest(root)
    for product in manifest["products"]:
        budget.charge(products=1)
        ids = set()
        for number, descriptor in enumerate(product["pages"]):
            budget.charge(pages=1, facts=descriptor["facts"], raw_bytes=descriptor["raw_bytes"],
                          compressed_bytes=descriptor["bytes"])
            for item in read_page(root, manifest, product, descriptor, number):
                require(item["fact_id"] not in ids, "duplicate fact across pages")
                ids.add(item["fact_id"])
        require(len(ids) == product["facts"], "snapshot product accounting mismatch")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = prepare_snapshot(args.database, args.contract, args.output)
    validate_snapshot(args.output)
    print(json.dumps({"result": "PASS", "scope": SCOPE, "publication_authorized": False,
                      "source": value["source"], "totals": value["totals"], "limits": asdict(Limits())}, sort_keys=True))


if __name__ == "__main__":
    main()
