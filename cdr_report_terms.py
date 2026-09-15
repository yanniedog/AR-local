"""Sealed optional report evidence. Integrity is not bank acceptance or activation."""
import argparse
import gzip
import io
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cdr_terms.identity import digest
from cdr_report_io import decode_json

VERSION = 'report-terms-evidence-v1'
MAX_BYTES = 24 * 1024 * 1024
MAX_PRODUCTS = 20000


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def bundle_binding(manifest, payloads, evidence):
    from app_payload_revisions_state import bundle_sha256
    source = manifest.get('source_observation') or {}
    revision = manifest.get('payload_revision')
    if revision and revision['bundle_sha256'] != bundle_sha256(manifest):
        raise ValueError('Report selected edition identity differs')
    keys = sorted(set(payloads['details']['products']) | {
        r['product_key'] for s in payloads['core']['sections'].values() for r in s['rates']})
    if len(keys) > MAX_PRODUCTS:
        raise ValueError('Report evidence product budget exceeded')
    return {'manifest_sha256': evidence['manifest_sha256'], 'edition': revision['bundle_sha256'] if revision else None,
            'binding_mode': 'immutable_edition' if revision else 'legacy_exact_manifest',
            'run_date': manifest['run_date'], 'core_sha256': manifest['files']['core']['sha256'],
            'details_sha256': manifest['files']['details']['sha256'],
            'source_generation_id': source.get('generation_id'), 'export_contract_sha256': source.get('contract_digest'),
            'product_inventory_sha256': digest(keys)}, keys


def asset_reader(root):
    used, decoded = 0, 0
    cache, names = {}, {}

    def read(descriptor):
        nonlocal used, decoded
        name = descriptor['name']
        if not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('Unsafe report evidence asset name')
        if name in names and names[name] != descriptor:
            raise ValueError('Contradictory report asset descriptor')
        names[name] = descriptor
        if name in cache:
            return cache[name]
        path = root / name
        if path.is_symlink() or path.stat().st_size > MAX_BYTES or used + path.stat().st_size > MAX_BYTES:
            raise ValueError('Report evidence compressed budget exceeded')
        raw = path.read_bytes()
        if len(raw) != descriptor['bytes'] or sha(raw) != descriptor['sha256']:
            raise ValueError('Report evidence asset identity differs')
        used += len(raw)
        if name.endswith('.gz'):
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                plain = stream.read(MAX_BYTES - decoded + 1)
        else:
            plain = raw
        decoded += len(plain)
        if decoded > MAX_BYTES:
            raise ValueError('Report evidence decoded budget exceeded')
        value = decode_json(plain, compressed=False, max_plain=MAX_BYTES)
        cache[name] = value
        return value
    return read


def delivered(root, manifest, payloads):
    """Record verified adopted assets only; never assert current private approval."""
    from cdr_terms.executable_contract import validate_asset as v1
    from cdr_terms.executable_v2_contract import validate_asset as v2
    from cdr_terms.executable_v3_contract import validate_asset as v3
    read = asset_reader(root)
    routes = []
    if 'executable_index' in manifest['files']:
        routes.append(('fixed_td_calculation', manifest['files']['executable_index'],
                       {k: d for k, d in manifest['files'].items() if k.startswith('executable_shard_')}, v1))
    if manifest.get('executable_v2'):
        n = manifest['executable_v2']
        routes.append(('eligibility_only', n['index'], n['shards'], v2))
    if manifest.get('executable_v3'):
        for capability, n in manifest['executable_v3']['capabilities'].items():
            if capability not in ('savings_calculation', 'mortgage_calculation'):
                raise ValueError('Unsupported report capability')
            routes.append((capability, n['index'], n['shards'], v3))
    result = {}
    for capability, descriptor, shards, validate in routes:
        index = read(descriptor)
        def header(value):
            if (value['run_date'] != manifest['run_date'] or value['core_asset_sha256'] != manifest['files']['core']['sha256']
                    or (capability != 'fixed_td_calculation' and value['details_asset_sha256'] != manifest['files']['details']['sha256'])
                    or (capability in ('savings_calculation', 'mortgage_calculation') and value['capability'] != capability)):
                raise ValueError('Report delivered route binding differs')
        header(index)
        if set(index['products'].values()) != set(shards):
            raise ValueError('Report delivered shard inventory differs')
        observed = {}
        for name, shard in sorted(shards.items()):
            value = read(shard)
            header(value)
            for key, asset in value['products'].items():
                if key in observed or index['products'].get(key) != name:
                    raise ValueError('Report delivered product association differs')
                validate(asset)
                if capability in ('savings_calculation', 'mortgage_calculation') and asset['capability'] != capability:
                    raise ValueError('Report delivered asset capability differs')
                if asset['productKey'] != key:
                    raise ValueError('Report delivered asset product differs')
                if capability == 'fixed_td_calculation':
                    if asset['coreAssetSha256'] != manifest['files']['core']['sha256']:
                        raise ValueError('Report delivered TD core differs')
                    subjects = [x['template'] for x in asset['templates']]
                else:
                    subjects = [x['subject'] for x in asset['subjects']]
                for subject in subjects:
                    if capability == 'fixed_td_calculation':
                        selected = subject['selectedRate']
                        rows = payloads['core']['sections']['TD']['rates']
                        row_index = selected['coreRowIndex']
                        if (selected['coreAssetSha256'] != manifest['files']['core']['sha256'] or not 0 <= row_index < len(rows)
                                or rows[row_index].get('product_key') != key or digest(rows[row_index]) != selected['rowSha256']
                                or rows[row_index].get('rate_index') != selected['rateIndex']):
                            raise ValueError('Report delivered TD row differs')
                    elif capability in ('savings_calculation', 'mortgage_calculation'):
                        from cdr_terms.executable_v3_sources import validate_destination
                        validate_destination(subject, payloads['core'], payloads['details'],
                                             manifest['files']['core']['sha256'], manifest['files']['details']['sha256'])
                    elif capability == 'eligibility_only':
                        from cdr_terms.executable_v2_sources import validate_destination
                        validate_destination(subject, payloads['core'], payloads['details'],
                                             core_sha=manifest['files']['core']['sha256'],
                                             details_sha=manifest['files']['details']['sha256'])
                observed[key] = True
                result.setdefault(key, []).append({'capability': capability, 'asset_sha256': shard['sha256'],
                                                   'subject_ids': sorted(s['id'] for s in subjects),
                                                   'status': 'delivered_as_of_selected_edition',
                                                   'bank_acceptance': 'unclassified'})
        if set(observed) != set(index['products']):
            raise ValueError('Report delivered index product inventory differs')
    return result


def export_evidence(bundle, store, output, *, technical=False):
    from cdr_product_report import read_bundle
    from cdr_report_terms_store import Snapshot
    bundle, store, output = Path(bundle).resolve(), Path(store).resolve(), Path(output).resolve()
    for source in (bundle, store):
        if output == source or output in source.parents or source in output.parents:
            raise ValueError('Evidence output must be separate from inputs')
    if output.exists():
        raise ValueError('Use a new immutable evidence directory')
    manifest, payloads, evidence = read_bundle(bundle)
    binding, keys = bundle_binding(manifest, payloads, evidence)
    adopted = delivered(bundle, manifest, payloads)
    if set(adopted) - set(keys):
        raise ValueError('Report delivered unknown product')
    view = Snapshot(store)
    try:
        members = view.capture(binding)
        products, total = {}, 0
        for key in keys:
            row = view.product(key, binding, members)
            row.update(evidence_class='technical_fixture' if technical else 'unclassified',
                       delivered=adopted.get(key, []), bank_approved=None)
            if row['status'] == 'reported':
                from cdr_report_terms_contract import inventory_stages
                row['stages'].update(inventory_stages(row))
            total += len(encoded(row)) + len(key.encode('utf-8'))
            if total > MAX_BYTES:
                raise ValueError('Report evidence output budget exceeded')
            products[key] = row
        value = {'schema_version': 1, 'contract': VERSION, 'binding': binding, 'products': products,
                 'generated_at': datetime.now(timezone.utc).isoformat(), 'snapshot': view.receipt(),
                 'exporter_code_sha256s': {name: sha(Path(__file__).with_name(name).read_bytes()) for name in
                    ('cdr_report_terms.py', 'cdr_report_terms_store.py', 'cdr_report_terms_contract.py')},
                 'bank_acceptance_policy': 'unclassified_unless_independently_verified; no upgrade supported in v1'}
    finally:
        view.close()
    from cdr_report_terms_contract import validate_rows
    validate_rows(products)
    body = encoded(value)
    if len(body) > MAX_BYTES:
        raise ValueError('Report evidence output budget exceeded')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.report-evidence-', dir=output.parent))
    try:
        (stage / 'evidence.json').write_bytes(body)
        seal = {'contract': VERSION, 'file': 'evidence.json', 'bytes': len(body), 'sha256': sha(body), 'products': len(keys)}
        (stage / 'seal.json').write_bytes(encoded(seal))
        from cdr_report_admission import admit_new_directory
        admit_new_directory(stage, output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return seal


def admit_evidence(root, binding, keys):
    root = Path(root).resolve()
    seal_path = root / 'seal.json'
    if seal_path.is_symlink() or seal_path.stat().st_size > 4096:
        raise ValueError('Report evidence seal invalid')
    seal = json.loads(seal_path.read_bytes())
    if (set(seal) != {'contract', 'file', 'bytes', 'sha256', 'products'} or seal['contract'] != VERSION
            or seal['file'] != 'evidence.json' or type(seal['bytes']) is not int or not 0 < seal['bytes'] <= MAX_BYTES):
        raise ValueError('Report evidence seal invalid')
    path = root / seal['file']
    if path.is_symlink() or path.stat().st_size != seal['bytes']:
        raise ValueError('Report evidence bytes differ')
    raw = path.read_bytes()
    if sha(raw) != seal['sha256']:
        raise ValueError('Report evidence hash differs')
    value = json.loads(raw)
    if encoded(value) != raw:
        raise ValueError('Report evidence must use canonical sealed JSON')
    if set(value) != {'schema_version', 'contract', 'binding', 'products', 'generated_at', 'snapshot',
                      'exporter_code_sha256s', 'bank_acceptance_policy'}:
        raise ValueError('Report evidence header contract invalid')
    from cdr_report_terms_contract import validate_header
    validate_header(value)
    if (value.get('schema_version') != 1 or value.get('contract') != VERSION or value.get('binding') != binding
            or set(value.get('products', {})) != set(keys) or seal['products'] != len(keys)):
        raise ValueError('Report evidence selected identity differs')
    from cdr_report_terms_contract import validate_rows
    validate_rows(value['products'])
    for row in value['products'].values():
        if row['evidence_class'] not in ('unclassified', 'technical_fixture') or row['bank_approved'] is not None:
            raise ValueError('Report evidence cannot promote bank acceptance')
    return value, seal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle', 'store', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--technical', action='store_true', help='Downgrade all rows to technical fixtures; never upgrade provenance.')
    args = parser.parse_args()
    print(json.dumps(export_evidence(args.bundle, args.store, args.output, technical=args.technical)))


if __name__ == '__main__':
    main()
