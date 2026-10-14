"""Detached bounded public pricing catalogue for a selected ingest generation."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from cdr_domain.public_pricing import canonical_bytes, semantic_id
from cdr_domain.public_pricing_validation import validate_programme, validate_wire

NAMESPACE = "public_rate_catalogue"
CANDIDATE_NAME = "public-rate-catalogue-candidate.json"
INDEX_COMPRESSED = 256 * 1024
INDEX_DECODED = 2 * 1024 * 1024
SHARD_COMPRESSED = 1024 * 1024
SHARD_DECODED = 4 * 1024 * 1024
CATALOGUE_DECODED = 24 * 1024 * 1024
BINDING_FIELDS = ("schemaVersion", "generationId", "runDate", "coreSha256", "detailsSha256")


def load_candidate(root: Path, *, source_observation: Mapping[str, Any] | None, run_date: str) -> dict:
    if not source_observation or not source_observation.get("generation_id"):
        raise ValueError("public catalogue requires a selected ingest generation")
    path = root if root.is_file() else root / CANDIDATE_NAME
    from cdr_public_rates_candidate import read_candidate
    try:
        candidate = read_candidate(path)
    except ValueError as exc:
        if 'filename_hash' in str(exc):
            raise ValueError('public catalogue candidate filename hash differs') from exc
        raise
    if (candidate.get("schemaVersion") != 1 or candidate.get("runDate") != run_date
            or candidate.get("generationId") != source_observation["generation_id"]):
        raise ValueError("public catalogue candidate belongs to another ingest generation")
    for field in ("products", "programmes", "referenceRates", "evidence", "coverage", "enabledProgrammeIds"):
        if not isinstance(candidate.get(field), list):
            raise ValueError("public catalogue candidate field missing: " + field)
    return candidate


def _descriptor(out_dir, kind, binding, value, release_base, compressed_limit, decoded_limit):
    raw = canonical_bytes(value)
    if len(raw) > decoded_limit:
        raise ValueError("public catalogue decoded asset budget exceeded")
    blob = gzip.compress(raw, compresslevel=9, mtime=0)
    if len(blob) > compressed_limit:
        raise ValueError("public catalogue compressed asset budget exceeded")
    digest = hashlib.sha256(blob).hexdigest()
    name = f"public-rate-{kind}-{binding['runDate']}-{digest[:12]}.json.gz"
    target = out_dir / name
    if target.exists() and target.read_bytes() != blob:
        raise ValueError("public catalogue immutable asset collision")
    from app_payload_revisions_github import write_once
    write_once(target, blob)
    return {"name": name, "url": release_base + "/" + name, "sha256": digest,
            "bytes": len(blob), "decodedBytes": len(raw), "encoding": "gzip"}


def _unique(items, field):
    result = {}
    for item in items:
        identity = item[field]
        if identity in result and result[identity] != item:
            raise ValueError("conflicting public catalogue identity: " + field)
        result[identity] = item
    return result


def package_catalogue(candidate: dict, *, out_dir: Path, release_base: str,
                      core_sha256: str, details_sha256: str, publication_receipt: Path | None = None) -> dict:
    """Only reviewed enabled programme IDs carry executable pricing formulas.

    Shadow candidate artefacts retain all formulae; packaging copies them and
    cannot promote an unapproved programme by changing its captured prices.
    """
    binding = {"schemaVersion": 1, "generationId": candidate["generationId"], "runDate": candidate["runDate"],
               "coreSha256": core_sha256, "detailsSha256": details_sha256}
    validate_wire(binding, 'Binding')
    products = _unique(deepcopy(candidate["products"]), "productId")
    from cdr_public_rates_candidate import programme_ids, selected_evidence, selected_programmes
    available_programmes = programme_ids(candidate)
    references = {}
    for reference in deepcopy(candidate["referenceRates"]):
        observation = reference.get("observationId") or semantic_id("reference-observation", reference)
        if observation in references and references[observation] != reference:
            raise ValueError("conflicting public reference observation identity")
        references[observation] = reference
    if candidate.get('enabledProgrammeIds'):
        raise ValueError('captured candidate data cannot activate public programmes')
    enabled = _authorised_programmes(candidate, publication_receipt)
    suspensions = getattr(enabled, 'suspensions', {})
    suspension_by_product = {}
    for item in suspensions.values():
        suspension_by_product.setdefault(item['productId'], set()).update(item['reasonCodes'])
    if not enabled <= available_programmes:
        raise ValueError("enabled public programme is not in this candidate")
    programmes = _unique(deepcopy(selected_programmes(candidate, enabled)), 'programmeId')
    needed_evidence = set()
    for programme in programmes.values():
        if programme["productId"] not in products:
            raise ValueError("public programme product identity is absent")
        if programme['programmeId'] not in products[programme['productId']]['programmeIds']:
            raise ValueError("public programme discovery binding is absent")
        if programme["programmeId"] in enabled:
            validate_programme(programme)
            if not programme.get("formula"):
                raise ValueError("enabled public programme has no executable pricing formula")
            needed = _needed_evidence(programme)
            if not needed:
                raise ValueError("enabled public pricing lacks complete evidence bindings")
            needed_evidence.update(needed)
    for product in products.values():
        if not set(product["programmeIds"]) <= available_programmes:
            raise ValueError("public discovery programme binding is absent")
        if not set(product["referenceIds"]) <= {r["referenceId"] for r in references.values()}:
            raise ValueError("public discovery reference binding is absent")
        if any(programmes[identity]['productId'] != product['productId'] for identity in set(product['programmeIds']) & enabled):
            raise ValueError("public discovery programme belongs to another product")
        suppressed = set(product['programmeIds']) - enabled
        product['programmeIds'] = sorted(set(product['programmeIds']) & enabled)
        product['suppressedProgrammeCount'] = product.get('suppressedProgrammeCount', 0) + len(suppressed)
        if product['suppressedProgrammeCount']:
            product['reasonCodes'] = sorted(set(product['reasonCodes']) | {'pricing_programme_not_enabled'})
        if product['productId'] in suspension_by_product:
            product['reasonCodes'] = sorted(set(product['reasonCodes']) | suspension_by_product[product['productId']])
        validate_wire(product, "Product")
    for item in references.values():
        validate_wire(item, "Reference")
        needed_evidence.update(item['evidenceIds'])
    try:
        evidence = _unique(deepcopy(selected_evidence(candidate, needed_evidence)), 'evidenceId')
    except ValueError as exc:
        raise ValueError('public pricing lacks complete evidence bindings') from exc
    if not needed_evidence <= set(evidence):
        raise ValueError('public pricing lacks complete evidence bindings')
    out_dir.mkdir(parents=True, exist_ok=True)
    fee_sets = _deduplicate_fees(programmes)
    discovery_assets, discovery_routes, discovery_routing = _write_discovery_shards(binding, products, out_dir, release_base)
    pricing_assets, pricing_routes, pricing_routing = _write_shards(
        binding, products, programmes, references, fee_sets, evidence, out_dir, release_base,
        start_index=len(discovery_assets))
    shards = [*discovery_assets, *pricing_assets]
    routes = [*discovery_routes, *pricing_routes]
    coverage = deepcopy(candidate["coverage"])
    for row in coverage:
        row["publicationStatus"] = "published"
        affected = [product for product in products.values() if product['productId'] in suspension_by_product
                    and product['providerId'] == row['providerId'] and product['section'] == row['section']]
        if affected:
            reasons = set().union(*(suspension_by_product[product['productId']] for product in affected))
            row['reasonCodes'] = sorted(set(row['reasonCodes']) | reasons)
            row['resolutionStatus'] = ('partial' if any(product['programmeIds'] for product in products.values()
                                                      if product['providerId'] == row['providerId'] and product['section'] == row['section'])
                                       else 'unresolved')
            row['publicationStatus'] = 'published_with_suspensions'
    # Full discovery records and cryptographic programme IDs belong in bounded
    # shards. Repeating them in the index exceeds its compressed budget even
    # with one programme per product in the current public inventory.
    index = {**binding, "products": [], "coverage": coverage, "shards": routes,
             "routes": [*discovery_routing, *pricing_routing]}
    validate_wire(index, "Index")
    index_asset = _descriptor(out_dir, "index", binding, index, release_base, INDEX_COMPRESSED, INDEX_DECODED)
    if index_asset["decodedBytes"] + sum(shard["decodedBytes"] for shard in shards) > CATALOGUE_DECODED:
        raise ValueError("complete public catalogue decoded budget exceeded")
    capability = {**binding, "index": index_asset, "shards": shards}
    validate_wire(capability, "Capability")
    return capability


def _authorised_programmes(candidate, receipt_path):
    from cdr_public_rates_publication import authorised_programmes
    return authorised_programmes(candidate, receipt_path)


def _deduplicate_fees(programmes):
    sets = {}
    for programme in programmes.values():
        if "fees" not in programme:
            continue
        fees = sorted(programme.pop("fees"), key=lambda fee: fee["feeId"])
        content = {"productId": programme["productId"], "fees": fees, "feeCoverage": programme.pop('feeCoverage')}
        identity = semantic_id("fee-set", content)
        sets[identity] = {"feeSetId": identity, **content}
        programme["feeSetId"] = identity
    return sets


def _route(asset, product_ids):
    return {**{key: value for key, value in asset.items() if key != 'url'}, 'productIds': sorted(product_ids)}


def _needed_evidence(value):
    identities = set()
    if isinstance(value, dict):
        identities.update(value.get('evidenceIds', []))
        for child in value.values():
            identities.update(_needed_evidence(child))
    elif isinstance(value, list):
        for child in value:
            identities.update(_needed_evidence(child))
    return identities


def _write_discovery_shards(binding, products, out_dir, release_base):
    assets, routes, routing, pending = [], [], [], []
    pending_bytes = [len(canonical_bytes(binding)) + 256]

    def flush():
        if not pending:
            return
        data = {**binding, 'products': pending, 'programmes': [], 'referenceRates': [], 'evidence': []}
        validate_wire(data, 'Shard')
        asset = _descriptor(out_dir, f'shard-{len(assets):04d}', binding, data, release_base,
                            SHARD_COMPRESSED, SHARD_DECODED)
        assets.append(asset)
        routes.append(_route(asset, []))
        routing.append({'name': asset['name'], 'kind': 'discovery',
                        'providerIds': sorted({product['providerId'] for product in pending}),
                        'sections': sorted({product['section'] for product in pending})})
        pending.clear()
        pending_bytes[0] = len(canonical_bytes(binding)) + 256

    for product in sorted(products.values(), key=lambda item: (item['providerId'], item['section'], item['productId'])):
        size = len(canonical_bytes(product)) + 1
        if pending_bytes[0] + size > SHARD_COMPRESSED - 64 * 1024:
            flush()
        pending.append(product)
        pending_bytes[0] += size
    flush()
    return assets, routes, routing


def _write_shards(binding, products, programmes, references, fee_sets, evidence, out_dir, release_base, *, start_index=0):
    shards, routes, routing = [], [], []
    pending_programmes, pending_refs, pending_fees, pending_evidence, pending_products = [], [], [], {}, set()
    pending_providers, pending_sections = set(), set()
    pending_bytes = [len(canonical_bytes(binding)) + 256]

    def value():
        return {**binding, "programmes": pending_programmes, "referenceRates": pending_refs, "feeSets": pending_fees,
                "evidence": sorted(pending_evidence.values(), key=lambda e: e["evidenceId"])}

    def flush():
        if not pending_programmes and not pending_refs and not pending_fees:
            return
        data = value()
        validate_wire(data, "Shard")
        asset = _descriptor(out_dir, f"shard-{start_index + len(shards):04d}", binding, data, release_base,
                            SHARD_COMPRESSED, SHARD_DECODED)
        shards.append(asset)
        routes.append(_route(asset, pending_products))
        routing.append({'name': asset['name'], 'kind': 'pricing', 'providerIds': sorted(pending_providers),
                        'sections': sorted(pending_sections)})
        pending_programmes.clear()
        pending_refs.clear()
        pending_fees.clear()
        pending_evidence.clear()
        pending_products.clear()
        pending_providers.clear()
        pending_sections.clear()
        pending_bytes[0] = len(canonical_bytes(binding)) + 256

    entries = [("programmes", p) for p in sorted(programmes.values(), key=lambda p: p["programmeId"])]
    entries.extend(("references", r) for r in sorted(references.values(), key=lambda r: r["referenceId"]))
    entries.extend(("fees", fee) for fee in sorted(fee_sets.values(), key=lambda fee: fee["feeSetId"]))
    for kind, entry in entries:
        needed = _needed_evidence(entry)
        additional = {eid: evidence[eid] for eid in needed if eid in evidence}
        for item in additional.values():
            validate_wire(item, 'Evidence')
        added_bytes = len(canonical_bytes(entry)) + sum(len(canonical_bytes(item)) + 1 for key, item in additional.items()
                                                       if key not in pending_evidence) + 1
        # A conservative uncompressed chunk ceiling avoids quadratic trial gzip
        # work and also bounds gzip expansion for adversarial low-compressibility
        # public text. The protocol's larger decoded ceiling stays unchanged.
        if pending_bytes[0] + added_bytes > SHARD_COMPRESSED - 64 * 1024:
            flush()
            added_bytes = len(canonical_bytes(entry)) + sum(len(canonical_bytes(item)) + 1 for item in additional.values()) + 1
        pending_bytes[0] += added_bytes
        (pending_programmes if kind == "programmes" else pending_refs if kind == "references" else pending_fees).append(entry)
        pending_evidence.update(additional)
        if kind in {"programmes", "fees"}:
            pending_products.add(entry["productId"])
            pending_providers.add(products[entry['productId']]['providerId'])
            pending_sections.add(products[entry['productId']]['section'])
        else:
            bound = [p for p in products.values() if entry['referenceId'] in p['referenceIds']]
            pending_products.update(p['productId'] for p in bound)
            pending_providers.add(entry['providerId'])
            pending_providers.update(p['providerId'] for p in bound)
            # Routes select downloads; they never confer pricing applicability.
            # Unbound reference families remain available in every local picker.
            pending_sections.update(p['section'] for p in bound)
            if not bound:
                pending_sections.update(('Mortgage', 'Savings', 'TD'))
    flush()
    return shards, routes, routing


def descriptor(manifest: Mapping[str, Any]) -> dict:
    capability = manifest[NAMESPACE]
    validate_wire(capability, "Capability")
    observation = manifest.get("source_observation", {})
    if (capability["generationId"] != observation.get("generation_id")
            or capability["runDate"] != manifest.get("run_date")
            or capability["coreSha256"] != manifest["files"]["core"]["sha256"]
            or capability["detailsSha256"] != manifest["files"]["details"]["sha256"]):
        raise ValueError("public catalogue binding differs from selected generation/core/details")
    if capability["index"]["bytes"] > INDEX_COMPRESSED or capability["index"]["decodedBytes"] > INDEX_DECODED:
        raise ValueError("public catalogue index budget exceeded")
    assets = [capability["index"], *capability["shards"]]
    if len({asset["name"] for asset in assets}) != len(assets):
        raise ValueError("public catalogue asset names must be unique")
    if sum(asset["decodedBytes"] for asset in assets) > CATALOGUE_DECODED:
        raise ValueError("complete public catalogue budget exceeded")
    base = f"https://github.com/{manifest['repo']}/releases/download/{manifest['tag']}/"
    if any(asset["url"] != base + asset["name"] for asset in assets):
        raise ValueError("public catalogue URL leaves its selected release")
    return capability


def iter_assets(manifest):
    capability = descriptor(manifest)
    yield "public_rate_catalogue_index", capability["index"]
    for index, shard in enumerate(capability["shards"]):
        yield f"public_rate_catalogue_shard_{index:04d}", shard


def identity_namespace(capability):
    return {**capability, "index": {k: v for k, v in capability["index"].items() if k != "url"},
            "shards": [{k: v for k, v in asset.items() if k != "url"} for asset in capability["shards"]]}


def retag(manifest, *, url):
    if NAMESPACE in manifest:
        capability = manifest[NAMESPACE]
        manifest[NAMESPACE] = {**capability, "index": {**capability["index"], "url": url(capability["index"]["name"])},
                               "shards": [{**asset, "url": url(asset["name"])} for asset in capability["shards"]]}


def _decode(root, asset, limit):
    path = root / asset["name"]
    if path.is_symlink() or path.resolve().parent != root.resolve():
        raise ValueError("public catalogue asset escapes its root")
    raw = path.read_bytes()
    if len(raw) != asset["bytes"] or hashlib.sha256(raw).hexdigest() != asset["sha256"]:
        raise ValueError("public catalogue asset hash or size differs")
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        decoded = stream.read(limit + 1)
    if len(decoded) > limit or len(decoded) != asset["decodedBytes"]:
        raise ValueError("public catalogue decoded budget or size differs")
    return json.loads(decoded)


def validate_local_catalogue(manifest, root: Path):
    capability = descriptor(manifest)
    index = _decode(root, capability["index"], INDEX_DECODED)
    validate_wire(index, "Index")
    binding = {field: capability[field] for field in BINDING_FIELDS}
    if any(index[field] != binding[field] for field in BINDING_FIELDS):
        raise ValueError("public catalogue index mixes generations")
    assets = {asset["name"]: asset for asset in capability["shards"]}
    if len(index['shards']) != len(assets) or set(assets) != {asset["name"] for asset in index["shards"]}:
        raise ValueError("public catalogue shard inventory differs")
    routing = {row['name']: row for row in index.get('routes', [])}
    if 'routes' in index and (len(routing) != len(index['routes']) or set(routing) != set(assets)):
        raise ValueError('public catalogue discovery routing differs')
    products = list(index['products'])
    programmes, reference_ids, fee_sets, pricing_routes = [], set(), {}, []
    for route in index["shards"]:
        asset = assets[route["name"]]
        if any(asset[field] != route[field] for field in ("sha256", "bytes", "decodedBytes", "encoding")):
            raise ValueError("public catalogue shard descriptor differs")
        shard = _decode(root, asset, SHARD_DECODED)
        validate_wire(shard, "Shard")
        if any(shard[field] != binding[field] for field in BINDING_FIELDS):
            raise ValueError("public catalogue shard mixes generations")
        metadata = routing.get(route['name'])
        if metadata and metadata['kind'] == 'discovery':
            if (route['productIds'] or any(shard.get(field, []) for field in ('programmes', 'referenceRates', 'evidence', 'feeSets'))
                    or set(metadata['providerIds']) != {p['providerId'] for p in shard.get('products', [])}
                    or set(metadata['sections']) != {p['section'] for p in shard.get('products', [])}):
                raise ValueError('public discovery shard routing or content differs')
        elif metadata:
            if shard.get('products'):
                raise ValueError('public pricing shard contains discovery records')
            pricing_routes.append((route, metadata, shard))
        products.extend(shard.get('products', []))
        programmes.extend(shard['programmes'])
        reference_ids.update(reference['referenceId'] for reference in shard['referenceRates'])
        for fee_set in shard.get('feeSets', []):
            if fee_set['feeSetId'] in fee_sets and fee_sets[fee_set['feeSetId']] != fee_set:
                raise ValueError('conflicting public fee set identity')
            fee_sets[fee_set['feeSetId']] = fee_set
        for programme in shard["programmes"]:
            validate_programme(programme)
        needed = _needed_evidence({'programmes': shard['programmes'], 'references': shard['referenceRates'], 'fees': shard.get('feeSets', [])})
        if not needed <= {item['evidenceId'] for item in shard['evidence']}:
            raise ValueError('public pricing shard evidence bindings differ')
    discovery = _unique(products, 'productId')
    resolved = _unique(programmes, 'programmeId')
    if len(discovery) != len(products) or len(resolved) != len(programmes):
        raise ValueError('duplicate public catalogue record identity')
    _validate_public_bindings(discovery, resolved, reference_ids, fee_sets, pricing_routes)
    return {"index": index, 'products': sorted(discovery.values(), key=lambda item: item['productId']),
            "decodedBytes": sum(asset["decodedBytes"] for asset in [capability["index"], *assets.values()])}


def _validate_public_bindings(products, programmes, reference_ids, fee_sets, pricing_routes):
    for product in products.values():
        if (not set(product['programmeIds']) <= set(programmes) or not set(product['referenceIds']) <= reference_ids
                or any(programmes[key]['productId'] != product['productId'] for key in product['programmeIds'])):
            raise ValueError('public discovery pricing bindings differ')
    for programme in programmes.values():
        product = products.get(programme['productId'])
        if not product or programme['programmeId'] not in product['programmeIds']:
            raise ValueError('public programme discovery binding differs')
        if 'feeSetId' in programme:
            fee_set = fee_sets.get(programme['feeSetId'])
            if not fee_set or fee_set['productId'] != programme['productId']:
                raise ValueError('public programme fee set binding differs')
    for route, metadata, shard in pricing_routes:
        ids = {item['productId'] for item in [*shard['programmes'], *shard.get('feeSets', [])]}
        ids.update(product['productId'] for product in products.values()
                   if set(product['referenceIds']) & {reference['referenceId'] for reference in shard['referenceRates']})
        if ids != set(route['productIds']) or not ids <= set(products):
            raise ValueError('public pricing product route differs')
        providers = {products[key]['providerId'] for key in ids}
        providers.update(reference['providerId'] for reference in shard['referenceRates'])
        sections = {products[key]['section'] for key in ids}
        if providers != set(metadata['providerIds']) or not sections <= set(metadata['sections']):
            raise ValueError('public pricing provider route differs')
