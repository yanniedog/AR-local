"""Offline searchable reports from one verified edition and its sealed terms parts."""
import argparse
import gzip
import io
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cdr_product_report import bank_inventory, field_inventory, inventory_products
from cdr_report_admission import admit_new_directory
from cdr_report_parts_html import index_html, part_html
from cdr_report_parts_io import MAX_FILE, Writer, csv_bytes, read_bundle, read_file
from cdr_report_terms import admit_evidence, bundle_binding, encoded, sha
from cdr_report_terms_parts import verify_parts

VERSION = 'combined-product-report-v1'
MAX_LEAVES = 2000000
CHUNK_ROWS = 5000
DEFINITIONS = '''# Definitions and verification boundaries

- Product denominator: exact union of selected core rate product keys and details keys.
- Rate rows: each published row, retaining its source section and zero-based row index.
- Detail presence: recorded separately; absent, null, empty, zero and false are distinct.
- Source metadata: every leaf outside core rate rows and detail product records, including all supplied auxiliary assets. JSON pointers identify original values; value_json preserves their types in CSV.
- Product summaries and field-presence counts are derived from the supplied edition. Source counts are retained separately and may differ.
- Rates retain their published field names, units and dates; no annual-to-monthly conversion or customer scenario calculation is performed.
- Document, clause and executable inventories describe captured evidence. Bank approval and complete legal/document/fee denominators remain unknown.
- Historical availability is limited to the supplied assets. Missing dates, observations and future rates are not inferred.
- CSV formula-like strings are prefixed with an apostrophe; canonical values remain in JSON and HTML.
- Integrity hashes do not establish bank authority. These files contain private evidence and are not automatically published.

Product JSON is gzip-compressed losslessly. HTML works offline and contains the same product records. Search all products by bank/name from the index; search every field within each part. Large detail and terms CSV files are also gzip-compressed.
'''


def leaves(value, pointer='', depth=0):
    if depth > 64:
        raise ValueError('Report field nesting budget exceeded')
    if isinstance(value, dict) and value:
        for key, item in value.items():
            token = key.replace('~', '~0').replace('/', '~1')
            yield from leaves(item, pointer + '/' + token, depth + 1)
    elif isinstance(value, list) and value:
        for i, item in enumerate(value):
            yield from leaves(item, pointer + '/' + str(i), depth + 1)
    else:
        yield pointer, value


def metadata_rows(payloads):
    for kind, payload in payloads.items():
        for pointer, value in leaves(payload):
            tokens = pointer.split('/')
            if kind == 'core' and len(tokens) >= 4 and tokens[1] == 'sections' and tokens[3] == 'rates':
                continue
            if kind == 'details' and len(tokens) >= 2 and tokens[1] == 'products':
                continue
            yield {'asset': kind, 'source_pointer': pointer, 'value': value}


def write_metadata(writer, payloads):
    descriptors, counts, batch = [], {}, []
    seen = batch_bytes = 0
    for row in metadata_rows(payloads):
        seen += 1
        if seen > MAX_LEAVES:
            raise ValueError('Report metadata row budget exceeded')
        counts[row['asset']] = counts.get(row['asset'], 0) + 1
        size = len(encoded(row)) + 1
        if batch and (len(batch) >= CHUNK_ROWS or batch_bytes + size > 2 * 1024**2):
            descriptors.extend(_metadata_chunk(writer, batch, len(descriptors) // 2 + 1))
            batch, batch_bytes = [], 0
        batch.append(row)
        batch_bytes += size
    if batch:
        descriptors.extend(_metadata_chunk(writer, batch, len(descriptors) // 2 + 1))
    return descriptors, counts


def _metadata_chunk(writer, rows, number):
    name = f'metadata/part-{number:04d}'
    plain = encoded(rows)
    csv = csv_bytes(({'asset': r['asset'], 'source_pointer': r['source_pointer'],
                      'value_json': encoded(r['value']).decode()} for r in rows),
                    ['asset', 'source_pointer', 'value_json'], json_fields=('value_json',))
    return [writer.write(name + '.json.gz', plain, compress=True, rows=len(rows)),
            writer.write(name + '.csv.gz', csv, compress=True, rows=len(rows))]


def product_rows(published, details, attached):
    for key, proof in attached['products'].items():
        item = published[key]
        summary = {**item['summary'], 'document_capture': proof['status'],
                   'executable_terms_coverage': 'reported_scopes' if any(d['subject_ids'] for d in proof['delivered']) else 'not_delivered',
                   'evidence_class': proof['evidence_class']}
        yield key, {**item, 'summary': summary, 'published_detail_present': key in details['products'],
                    'terms_evidence': proof}


def write_product_part(writer, name, value):
    rows = value['products']
    writer.write(name + '/product-data.json.gz', encoded(value), compress=True, rows=len(rows))
    writer.write(name + '/report.html', part_html(name, value), rows=len(rows))
    summaries = [row['summary'] for row in rows.values()]
    fields = sorted({key for row in summaries for key in row})
    writer.write(name + '/products.csv', csv_bytes(summaries, fields), rows=len(rows))
    rates = [rate for row in rows.values() for rate in row['rates']]
    writer.write(name + '/rates.csv', csv_bytes(({'product_key': r['product_key'], 'section': r['section'],
                 'published_row_index': r['published_row_index'], 'record_json': encoded(r).decode()} for r in rates),
                 ['product_key', 'section', 'published_row_index', 'record_json'], json_fields=('record_json',)), rows=len(rates))
    parameters = []
    for key, row in rows.items():
        for pointer, scalar in leaves(row['detail']):
            if len(parameters) >= MAX_LEAVES:
                raise ValueError('Report detail row budget exceeded')
            parameters.append({'product_key': key, 'source_pointer': pointer, 'value_json': encoded(scalar).decode()})
    writer.write(name + '/parameters.csv.gz', csv_bytes(parameters, ['product_key', 'source_pointer', 'value_json'], json_fields=('value_json',)),
                 compress=True, rows=len(parameters))
    writer.write(name + '/terms.csv.gz', csv_bytes(({'product_key': k, 'evidence_json': encoded(r['terms_evidence']).decode()}
                 for k, r in rows.items()), ['product_key', 'evidence_json'], json_fields=('evidence_json',)), compress=True, rows=len(rows))
    return len(rates)


def _render(stage, bundle, terms):
    manifest, payloads, evidence = read_bundle(bundle)
    binding, keys = bundle_binding(manifest, payloads, evidence)
    index = verify_parts(terms, binding, keys)
    products, rates, full = inventory_products(payloads['core'], payloads['details'])
    published = {row['summary']['product_key']: row for row in full}
    if sorted(published) != keys or len(published) != len(full):
        raise ValueError('Report published product inventory differs')
    writer, links, seen, rate_count = Writer(stage), [], [], 0
    for part in index['parts']:
        attached, seal = admit_evidence(terms / part['name'], binding, part['keys'])
        if seal != part['seal']:
            raise ValueError('Report source evidence changed during rendering')
        rows = dict(product_rows(published, payloads['details'], attached))
        value = {'contract': VERSION, 'binding': binding, 'source_terms_seal': seal, 'products': rows}
        rate_count += write_product_part(writer, part['name'], value)
        seen.extend(rows)
        for position, (key, row) in enumerate(rows.items()):
            links.append({'product_key': key, 'provider': row['summary']['provider'],
                          'product_name': row['summary']['product_name'], 'rate_rows': len(row['rates']),
                          'href': part['name'] + '/report.html#p' + str(position)})
    if seen != keys or rate_count != len(rates):
        raise ValueError('Report complete product/rate inventory differs')
    return _finish(writer, manifest, payloads, evidence, binding, index, links, products, rates)


def _finish(writer, manifest, payloads, evidence, binding, index, links, products, rates):
    metadata, metadata_counts = write_metadata(writer, payloads)
    writer.write('products.csv', csv_bytes(links, ['product_key', 'provider', 'product_name', 'rate_rows', 'href']), rows=len(links))
    banks, fields = bank_inventory(products, payloads['core']), field_inventory(rates, payloads['details'])
    for name, rows in [('banks', banks), ('fields', fields)]:
        writer.write(name + '.json.gz', encoded(rows), compress=True, rows=len(rows))
        writer.write(name + '.csv', csv_bytes(rows, sorted({k for row in rows for k in row})), rows=len(rows))
    writer.write('source-manifest.json', encoded(manifest))
    writer.write('definitions.md', DEFINITIONS.encode())
    writer.write('index.html', index_html({'binding': binding, 'run_date': manifest['run_date'],
                 'products': links, 'rate_rows': len(rates), 'parts': len(index['parts']), 'metadata': metadata}))
    receipt = {'contract': VERSION, 'binding': binding, 'generated_at': datetime.now(timezone.utc).isoformat(),
               'products': len(links), 'rate_rows': len(rates), 'parts': len(index['parts']),
               'metadata_leaf_counts': metadata_counts, 'source_evidence': evidence,
               'source_terms_index_sha256': sha(encoded(index)), 'files': list(writer.files),
               'total_asset_bytes': writer.total, 'expanded_asset_bytes': writer.expanded,
               'financial_acceptance': 'unverified', 'bank_approval': None,
               'code_sha256s': {name: sha(Path(__file__).with_name(name).read_bytes()) for name in
                   ('cdr_product_report_parts.py', 'cdr_report_parts_io.py', 'cdr_report_parts_html.py')}}
    writer.write('manifest.json', encoded(receipt))
    verify_report(writer.root, receipt)
    return receipt


def verify_report(root, receipt):
    """Re-read every output hash and independently reconstruct emitted inventories."""
    keys, rates = [], 0
    for descriptor in receipt['files']:
        raw = read_file(root / descriptor['file'], MAX_FILE)
        if len(raw) != descriptor['bytes'] or sha(raw) != descriptor['sha256']:
            raise ValueError('Rendered report file identity differs')
        if descriptor['file'].endswith('/product-data.json.gz'):
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                plain = stream.read(MAX_FILE + 1)
            if len(plain) > MAX_FILE or sha(plain) != descriptor['expanded_sha256']:
                raise ValueError('Rendered report expanded identity differs')
            value = json.loads(plain)
            if value['binding'] != receipt['binding']:
                raise ValueError('Rendered report edition differs')
            keys.extend(value['products'])
            rates += sum(len(row['rates']) for row in value['products'].values())
    from cdr_terms.identity import digest
    if (len(keys) != len(set(keys)) or len(keys) != receipt['products'] or keys != sorted(keys)
            or digest(keys) != receipt['binding']['product_inventory_sha256'] or rates != receipt['rate_rows']):
        raise ValueError('Rendered report inventory differs')


def generate(bundle, terms, output):
    bundle, terms, output = (Path(p).resolve() for p in (bundle, terms, output))
    for source in (bundle, terms):
        if output == source or output in source.parents or source in output.parents:
            raise ValueError('Report output must be separate from all inputs')
    if output.exists():
        raise ValueError('Use a new immutable report directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.combined-report-', dir=output.parent))
    try:
        receipt = _render(stage, bundle, terms)
        admit_new_directory(stage, output)
        return receipt
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle', 'terms-evidence', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    receipt = generate(args.bundle, args.terms_evidence, args.output)
    print(json.dumps({key: receipt[key] for key in ('contract', 'products', 'rate_rows', 'parts', 'total_asset_bytes')}))


if __name__ == '__main__':
    main()
