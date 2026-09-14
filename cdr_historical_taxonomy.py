"""Prepare a private, additive taxonomy candidate for exact retained May13 bytes.

No publication or runtime entrypoint exists. Only taxonomy_path may change;
details, prices, row order and identities are preserved. Unknowns stay unknown.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

import cdr_historical_taxonomy_rules as rules

OBSERVATION_DATE = '2026-05-13'
SOURCE_SHA = '5da7f5ebc1ee11591a062b086757a737d4da92c9fbc95e44e0214e38823b73d6'
ASSET_SHA = {
    'manifest.json': 'c6807bfaa3559479036e4d7c69048267a1fc145747c2275e064d02a0129c56a8',
    'core.json.gz': '3f291b09725d3b3ca8235e2aeb8641d78ed9e058d95f63572b778058b5e1b390',
    'details.json.gz': 'e77a7394a8221daa6f8ebd479fc3ff06dfb718f00d53d8a2569af205f8ca837a',
}
SOURCE_LIMIT = 96 * 1024**2
ASSET_LIMIT = 16 * 1024**2


def sha(body):
    return hashlib.sha256(body).hexdigest()


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON key')
        value[key] = item
    return value


def decode(body, *, compressed=False):
    if compressed:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            body = stream.read(SOURCE_LIMIT + 1)
    if len(body) > SOURCE_LIMIT:
        raise ValueError('JSON exceeds byte bound')
    return json.loads(body, object_pairs_hook=_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def read_bound(path, expected, limit):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('input missing, symlinked or oversized')
    with path.open('rb') as stream:
        body = stream.read(limit + 1)
    if len(body) > limit or sha(body) != expected:
        raise ValueError('input hash mismatch')
    return body


def exact(left, right):
    """Type-exact structural comparison: false, zero and missing remain distinct."""
    return rules.digest(left) == rules.digest(right)


def _published_value_matches(left, right):
    if exact(left, right):
        return True
    # Older export serialization can differ in decimal representation only.
    # No scaling, rounding, cleaning, default or other transformation occurs.
    first, second = rules.decimal(left), rules.decimal(right)
    return first is not None and second is not None and first == second


def _unique(items, key):
    result = {}
    for index, item in enumerate(items):
        identity = key(item)
        if identity in result:
            raise ValueError('ambiguous retained identity')
        result[identity] = (index, item)
    return result


def _source_records(source, details):
    products = _unique(source['products'], lambda item: item['product_key'])
    if set(products) != set(details['products']):
        raise ValueError('retained and public product membership differs')
    decoded = {}
    for key, (index, product) in products.items():
        record = decode(product['details_json'].encode())
        for raw, field in [('productId', 'product_id'), ('name', 'product_name'),
                           ('productCategory', 'category')]:
            if not exact(record.get(raw), product.get(field)):
                raise ValueError('embedded product identity differs')
        if key != '|'.join(str(product[field]) for field in (
                'provider', 'product_id', 'category', 'product_name')):
            raise ValueError('qualified product key differs')
        decoded[key] = (index, product, record)
    rates = _unique(source['rates'], lambda item: (
        item['product_key'], item['rate_family'], item['rate_index']))
    for key, family, index in rates:
        if key not in decoded or family not in {'lending', 'deposit'} or type(index) is not int or index < 1:
            raise ValueError('invalid source rate identity')
        record = decoded[key][2]
        array = record.get('lendingRates' if family == 'lending' else 'depositRates')
        if not isinstance(array, list) or index > len(array) or not isinstance(array[index - 1], dict):
            raise ValueError('embedded rate array membership differs')
    return decoded, rates


def verify_invariants(original, candidate):
    """Fail if any non-taxonomy value, position, container or multiplicity changes."""
    stripped = copy.deepcopy(candidate)
    if set(original['sections']) != set(candidate['sections']):
        raise ValueError('section membership changed')
    changes = 0
    for section, content in original['sections'].items():
        before, after = content['rates'], stripped['sections'][section]['rates']
        if len(before) != len(after):
            raise ValueError('row count changed')
        for old, new in zip(before, after):
            if not exact(old, new):
                changes += 1
            if 'taxonomy_path' in old:
                if not exact(old['taxonomy_path'], new.get('taxonomy_path')):
                    raise ValueError('existing taxonomy was overwritten')
                new['taxonomy_path'] = old['taxonomy_path']
            else:
                new.pop('taxonomy_path', None)
    if not exact(original, stripped):
        raise ValueError('non-taxonomy field, order or identity changed')
    return changes


def transform(source, core, details):
    """Pure transformation; prepare() independently pins the complete input bytes."""
    if any(item.get('run_date') != OBSERVATION_DATE for item in (source, core, details)):
        raise ValueError('observation date differs')
    if any(type(item.get('schema_version')) is not int or item['schema_version'] != 1
           for item in (core, details)):
        raise ValueError('unsupported payload schema')
    if set(core['sections']) != {'Mortgage', 'Savings', 'TD'}:
        raise ValueError('unexpected public sections')
    products, rates = _source_records(source, details)
    candidate, dispositions, seen = copy.deepcopy(core), [], set()
    for section, content in core['sections'].items():
        family = 'lending' if section == 'Mortgage' else 'deposit'
        for index, row in enumerate(content['rates']):
            identity = row['product_key'], family, row['rate_index']
            if type(row['rate_index']) is not int or identity in seen or identity not in rates:
                raise ValueError('public rate membership missing or ambiguous')
            seen.add(identity)
            source_index, retained = rates[identity]
            if any(field not in retained or not exact(value, retained[field])
                   for field, value in row.items() if field != 'taxonomy_path'):
                raise ValueError('published row conflicts with retained source')
            product_index, product, raw = products[row['product_key']]
            result = rules.classify(raw, family, row['rate_index'] - 1)
            proposed = result.pop('taxonomy_path')
            status = 'UNRESOLVED'
            if 'taxonomy_path' in row:
                status = 'EXISTING_TAXONOMY_PRESERVED'
            elif proposed is not None:
                candidate['sections'][section]['rates'][index]['taxonomy_path'] = proposed
                status = 'ADDED'
            raw_pointer = f"/{'lendingRates' if family == 'lending' else 'depositRates'}/{row['rate_index'] - 1}"
            raw_rate = raw[raw_pointer.split('/')[1]][row['rate_index'] - 1]
            dispositions.append({
                'status': status, 'product_key': row['product_key'], 'section': section,
                'public_row_pointer': f'/sections/{section}/rates/{index}',
                'public_row_sha256_before': rules.digest(row),
                'source_rate_pointer': f'/rates/{source_index}',
                'source_rate_sha256': rules.digest(retained),
                'source_product_pointer': f'/products/{product_index}',
                'embedded_string_pointer': f'/products/{product_index}/details_json',
                'embedded_string_utf8_sha256': sha(product['details_json'].encode()),
                'embedded_rate_pointer': raw_pointer, 'embedded_rate_sha256': rules.digest(raw_rate),
                'rate_values_already_differed_from_embedded_source': not _published_value_matches(
                    raw_rate.get('rate'), retained['rate']),
                'published_rate_preserved': row.get('rate'), 'embedded_rate_value': raw_rate.get('rate'),
                'before_present': 'taxonomy_path' in row, 'before': row.get('taxonomy_path'),
                'after': proposed if status == 'ADDED' else row.get('taxonomy_path'), **result})
    changes = verify_invariants(core, candidate)
    if changes != sum(item['status'] == 'ADDED' for item in dispositions):
        raise ValueError('change receipt differs from actual candidate')
    counts = Counter(item['status'] for item in dispositions)
    summary = {'public_rows': len(dispositions), 'source_rates': len(rates), 'source_products': len(products),
               'published_products_with_rates': len({key for key, _, _ in seen}),
               'rows_added': changes, 'disposition_counts': dict(counts),
               'section_disposition_counts': {section: dict(Counter(item['status'] for item in dispositions
                     if item['section'] == section)) for section in core['sections']},
               'unresolved_reason_counts': dict(Counter(reason for item in dispositions
                     if item['status'] == 'UNRESOLVED' for reason in item['unresolved_reasons'])),
               'existing_rate_transformations_preserved': sum(
                     item['rate_values_already_differed_from_embedded_source'] for item in dispositions),
               'non_taxonomy_values_order_and_multiplicity_unchanged': True}
    return candidate, dispositions, summary


def prepare(source_path: Path, released: Path, output: Path):
    source_path, released, output = source_path.resolve(), released.resolve(), output.resolve()
    roots = (source_path.parent, released)
    if output.exists() or any(output == root or root in output.parents or output in root.parents for root in roots):
        raise ValueError('new separate candidate directory required')
    body = read_bound(source_path, SOURCE_SHA, SOURCE_LIMIT)
    inputs = {name: read_bound(released / name, checksum, ASSET_LIMIT) for name, checksum in ASSET_SHA.items()}
    manifest = decode(inputs['manifest.json'])
    if manifest['run_date'] != OBSERVATION_DATE:
        raise ValueError('manifest observation date differs')
    for kind in ('core', 'details'):
        asset, declared = inputs[f'{kind}.json.gz'], manifest['files'][kind]
        if declared['sha256'] != sha(asset) or declared['bytes'] != len(asset):
            raise ValueError('manifest asset agreement failed')
    source, core, details = decode(body), decode(inputs['core.json.gz'], compressed=True), decode(
        inputs['details.json.gz'], compressed=True)
    candidate, dispositions, summary = transform(source, core, details)
    expected = {'public_rows': 10405, 'source_rates': 10548, 'source_products': 1633,
                'existing_rate_transformations_preserved': 38}
    if any(summary[key] != value for key, value in expected.items()):
        raise ValueError('exact May13 source population differs')
    candidate_bytes = gzip.compress(json.dumps(candidate, ensure_ascii=False,
                    separators=(',', ':'), allow_nan=False).encode(), mtime=0)
    # Recheck all originals before the first output write. Never open their DB,
    # image or mutable filesystem; this tool only consumes the recovered copy.
    read_bound(source_path, SOURCE_SHA, SOURCE_LIMIT)
    for name, checksum in ASSET_SHA.items():
        read_bound(released / name, checksum, ASSET_LIMIT)
    receipt = {'schema_version': 1, 'result': 'CANDIDATE_ONLY', 'publication': 'NOT_ATTEMPTED',
               'observation_date': OBSERVATION_DATE, 'change_kind': 'extraction_correction',
               'legal_amendment': False, 'source_export_sha256': SOURCE_SHA,
               'source_asset_sha256': ASSET_SHA, 'rule_version': rules.RULE_VERSION,
               'tool_source_sha256': {path.name: sha(path.read_bytes()) for path in (
                    Path(__file__), Path(rules.__file__))},
               'candidate_core_sha256': sha(candidate_bytes), 'candidate_core_bytes': len(candidate_bytes),
               'details_bytes_unchanged': True, **summary,
               'limitations': [
                   'Only taxonomy_path additions; all existing rate transformations retained verbatim.',
                   'Evidence pointers address the decoded retained embedded data object, not original HTTP bytes.',
                   'LVR tokens bucket the upper boundary; exact bounds remain in evidence and do not prove eligibility.',
                   'Unknown account kinds, components, ranges, payment exceptions and unreviewed text remain unresolved.',
                   'No date/name/default twelve-month or absent-tier flat-balance inference.',
                   'No full terms, PDS, fee, calculation or current applicability completeness claim.',
                   'Independent review, higher immutable revision and consumer/Pi acceptance required.']}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'core-candidate.json.gz').write_bytes(candidate_bytes)
    (output / 'details.json.gz').write_bytes(inputs['details.json.gz'])
    lines = ''.join(json.dumps(item, ensure_ascii=False, separators=(',', ':')) + '\n' for item in dispositions)
    (output / 'row-dispositions.jsonl').write_text(lines, encoding='utf-8')
    (output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    files = {path.name: {'sha256': sha(path.read_bytes()), 'bytes': path.stat().st_size}
             for path in sorted(output.iterdir())}
    (output / 'artifact-manifest.json').write_text(json.dumps(files, indent=2), encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recovered-export', type=Path, required=True)
    parser.add_argument('--released-audit-date', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.recovered_export, args.released_audit_date, args.output)))


if __name__ == '__main__':
    main()
