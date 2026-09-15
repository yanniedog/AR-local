"""Reproducible, exhaustive inventory of the bytes actually supplied to AR-app.

Read-only input. Produces a separate report directory, never an ingest export or
publication. Source counts and shipped fields have separate denominators.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from cdr_product_report_html import write_html
from cdr_report_io import MAX_ASSET_BYTES, decode_json

GROUPS = ('fees', 'features', 'eligibility', 'constraints', 'facts')


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bundle(root: Path) -> tuple[dict, dict, dict]:
    raw = (root / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    payloads, evidence = {}, {'manifest_sha256': digest(raw), 'assets': {}}
    for kind, asset in manifest['files'].items():
        name = asset['name']
        if Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('unsafe manifest asset name')
        if (root / name).stat().st_size > MAX_ASSET_BYTES:
            raise ValueError('manifest asset exceeds report input bound')
        data = (root / name).read_bytes()
        if len(data) != asset['bytes'] or digest(data) != asset['sha256']:
            raise ValueError('manifest asset mismatch: ' + kind)
        payload = decode_json(data, compressed=name.endswith('.gz'))
        if (kind in ('core', 'details') or 'run_date' in payload) and payload.get('run_date') != manifest['run_date']:
            raise ValueError('mixed dated bundle: ' + kind)
        payloads[kind] = payload
        evidence['assets'][kind] = {'name': name, 'bytes': len(data),
                                  'sha256': digest(data), 'url': asset['url']}
    return manifest, payloads, evidence


def present(value) -> bool:
    return value is not None and value != '' and value != [] and value != {}


def leaves(value, pointer=''):
    if isinstance(value, dict) and value:
        for key, item in value.items():
            token = key.replace('~', '~0').replace('/', '~1')
            yield from leaves(item, pointer + '/' + token)
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from leaves(item, pointer + '/' + str(index))
    else:
        yield pointer, value


def identity(key: str, rates: list[dict]) -> dict:
    if rates:
        first = rates[0]
        return {field: first.get(field, '') for field in
                ('provider', 'product_id', 'product_name', 'category')}
    parts = key.split('|', 3)
    if len(parts) != 4:
        return {'provider': '', 'product_id': '', 'product_name': key, 'category': ''}
    return dict(zip(('provider', 'product_id', 'category', 'product_name'), parts))


def inventory_products(core: dict, details: dict) -> tuple[list, list, list]:
    grouped = defaultdict(list)
    rows = []
    for section, value in core['sections'].items():
        for index, rate in enumerate(value['rates']):
            record = {'section': section, 'published_row_index': index, **rate}
            grouped[rate['product_key']].append(record)
            rows.append(record)
    products, full = [], []
    for key in sorted(set(grouped) | set(details['products'])):
        rates, detail = grouped[key], details['products'].get(key)
        fields = sorted({field for row in rates for field, value in row.items() if present(value)})
        product = {'product_key': key, **identity(key, rates),
                   'sections': '|'.join(sorted({r['section'] for r in rates})),
                   'published_rate_rows': len(rates), 'detail_present': detail is not None,
                   'rate_fields_reported': '|'.join(fields),
                   'detail_fields_reported': '|'.join(sorted(detail or {})),
                   'document_capture': 'not_reported',
                   'executable_terms_coverage': 'not_reported'}
        # Rate availability is not product membership. Combined transaction and
        # savings categories remain unknown without an observed rate section.
        category_family = {'TERM_DEPOSITS': 'TD', 'RESIDENTIAL_MORTGAGES': 'Mortgage'}.get(product['category'], '')
        product['product_families'] = product['sections'] or category_family
        product['family_basis'] = ('published_rate_section' if rates else
                                   'reported_category' if category_family else 'unknown')
        for group in GROUPS:
            product[group + '_entries'] = len((detail or {}).get(group, []))
        product['official_links'] = len((detail or {}).get('links', {}))
        product['source_documents'] = len((detail or {}).get('sourceDocuments', []))
        products.append(product)
        full.append({'summary': product, 'rates': rates, 'detail': detail})
    return products, rows, full


def bank_inventory(products, core):
    by_bank = defaultdict(list)
    for product in products:
        by_bank[product['provider']].append(product)
    failures = defaultdict(list)
    for item in core.get('coverage', {}).get('provider_failures', []):
        failures[item['provider']].append(item)
    result = []
    for bank in sorted(set(by_bank) | set(failures) | set(core.get('brands', {}))):
        items = by_bank[bank]
        result.append({'provider': bank, 'products_in_details_or_rates': len(items),
                       'products_with_rates': sum(p['published_rate_rows'] > 0 for p in items),
                       'published_rate_rows': sum(p['published_rate_rows'] for p in items),
                       **{group + '_entries': sum(p[group + '_entries'] for p in items)
                          for group in GROUPS},
                       'products_with_links': sum(p['official_links'] > 0 for p in items),
                       'failure_records': sum(i.get('count', 1) for i in failures[bank]),
                       'failure_details': failures[bank],
                       'document_completeness': 'unknown',
                       'population_source': 'public brands, details, rates and failures'})
    return result


def field_inventory(rows, details):
    counts = Counter()
    for row in rows:
        for field, value in row.items():
            if present(value):
                counts[('rate', field)] += 1
    for detail in details['products'].values():
        for field, value in detail.items():
            if present(value):
                counts[('product_detail', field)] += 1
    return [{'record_type': kind, 'field': field, 'present_records': count,
             'denominator': len(rows) if kind == 'rate' else len(details['products'])}
            for (kind, field), count in sorted(counts.items())]


def historical_rows(payloads):
    for kind in ('bank_history', 'bank_spread_history', 'history_banks', 'rba_calendar'):
        if kind not in payloads:
            continue
        payload = payloads[kind]
        dates = payload.get('run_dates', [])
        for pointer, value in leaves(payload):
            tokens = pointer.split('/')
            observed_date = ''
            if tokens[-1].isdigit() and len(dates) > int(tokens[-1]):
                # Only parallel primitive metric arrays use the date axis.
                parent = payload
                for token in tokens[1:-1]:
                    parent = parent[int(token)] if isinstance(parent, list) else parent[token.replace('~1', '/').replace('~0', '~')]
                if isinstance(parent, list) and len(parent) == len(dates) and all(not isinstance(x, (dict, list)) for x in parent):
                    observed_date = dates[int(tokens[-1])]
            yield {'asset': kind, 'source_pointer': pointer,
                   'observation_date': observed_date, 'value': value,
                   'value_type': type(value).__name__}


def detail_rows(full):
    for product in full:
        summary = product['summary']
        for pointer, value in leaves(product['detail']):
            yield {'provider': summary['provider'], 'product_key': summary['product_key'],
                   'product_name': summary['product_name'], 'source_pointer': pointer,
                   'value': value, 'value_type': type(value).__name__,
                   'status': 'published_cdr_field; document_semantics_not_verified'}


def write_csv(path, rows, fields=None):
    iterator = iter(rows)
    first = next(iterator, None)
    opener = gzip.open if path.suffix == '.gz' else open
    if first is None:
        with opener(path, 'wt', encoding='utf-8-sig', newline='') as stream:
            stream.write('')
        return 0
    columns = fields or list(first)
    count = 0
    with opener(path, 'wt', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in _chain(first, iterator):
            serialized = {key: json.dumps(value, ensure_ascii=False, separators=(',', ':'))
                          if isinstance(value, (dict, list)) else value
                          for key, value in row.items()}
            # CSV is raw tabulation, not executable formula content. Preserve the
            # original exact value separately in JSON evidence and quote formulas.
            for key, value in serialized.items():
                if isinstance(value, str) and value[:1] in ('=', '+', '-', '@', '\t', '\r'):
                    serialized[key] = "'" + value
            writer.writerow(serialized)
            count += 1
    return count


def _chain(first, iterator):
    yield first
    yield from iterator


def date_coverage(root, manifest):
    from cdr_history_validation import ordered_dates
    path = root / 'dates-index.json'
    if not path.is_file():
        return {'status': 'index_not_supplied'}
    raw = path.read_bytes()
    index = json.loads(raw)
    dates = ordered_dates(index)
    expected = []
    cursor, end = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    while cursor <= end:
        expected.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return {'index_sha256': digest(raw), 'dates': dates, 'date_count': len(dates),
            'selected_heads': index.get('revision_heads', {}),
            'missing_calendar_dates': sorted(set(expected) - set(dates)),
            'status': 'public_index_inventory; individual_dated_cores_not_checked',
            'latest_matches_bundle': dates[-1] == manifest['run_date']}


def attach_history(report: dict, source: Path, output: Path):
    """Join the completed dated audit only when its selected index is identical."""
    from cdr_history_validation import verified_exports
    raw = (source / 'summary.json').read_bytes()
    summary = json.loads(raw)
    if summary['index_sha256'] != report['historical_coverage']['index_sha256']:
        raise ValueError('historical audit uses a different selected date index')
    if sorted(item['run_date'] for item in summary['results']) != report['historical_coverage']['dates']:
        raise ValueError('historical audit omits or duplicates selected dates')
    if not summary['results'] or any(item.get('status') != 'PASS' for item in summary['results']):
        raise ValueError('historical audit contains failed selected dates')
    if type(summary.get('dates_passed')) is not int or summary['dates_passed'] != len(summary['results']):
        raise ValueError('historical audit passed-date count is inconsistent')
    exports = verified_exports(source, summary)
    selected_dates = {item['run_date']: item['status'] for item in summary['results']}
    _validate_history_dates(exports['dates.csv'], selected_dates)
    audited = {'summary_sha256': digest(raw), **summary, 'exports': {}}
    by_bank = defaultdict(lambda: {'dates': set(), 'products': set(), 'rate_rows': 0, 'observations': 0})
    for row in _history_csv_rows(exports['bank-product-dates.csv'], 'bank-product-dates.csv',
                                 {'provider', 'run_date', 'product_key', 'rate_rows'}, allow_empty=True):
        if row['run_date'] not in selected_dates:
            raise ValueError('historical audit bank-product-dates.csv contains an unselected date')
        bank = by_bank[row['provider']]
        bank['dates'].add(row['run_date'])
        bank['products'].add(row['product_key'])
        bank['rate_rows'] += int(row['rate_rows'])
        bank['observations'] += 1
    historical_banks = [
        {'provider': provider, 'observed_dates': len(bank['dates']),
         'first_observed_date': min(bank['dates']), 'last_observed_date': max(bank['dates']),
         'distinct_product_keys': len(bank['products']), 'product_section_days': bank['observations'],
         'rate_row_observations': bank['rate_rows'], 'absence_meaning': 'not_determined'}
        for provider, bank in sorted(by_bank.items())]
    # Parameters can fail only after streaming millions of rows. Stage them on
    # disk so validation finishes before changing the report or its outputs.
    with tempfile.TemporaryDirectory(prefix='.historical-report-', dir=output.parent) as temporary:
        stage = Path(temporary)
        row_counts = _prepare_history_exports(stage, source, summary, raw, exports, historical_banks, audited)
        _admit_history_exports(stage, output)
    report['historical_banks'] = historical_banks
    report['export_row_counts'].update(row_counts)
    report['historical_coverage']['individual_dated_audit'] = audited
    report['historical_coverage']['status'] = 'selected_dated_assets_audited; source_accuracy_and_missing_dates_unresolved'


def _history_csv_rows(body, name, required, *, allow_empty=False):
    """Parse verified bytes once, refusing ambiguous headers and malformed rows."""
    try:
        text = body.decode('utf-8-sig')
        if allow_empty and not text:  # write_csv emits only a BOM for zero observations.
            return
        with io.StringIO(text, newline='') as stream:
            reader = csv.reader(stream, strict=True)
            fields = next(reader, [])
            if (not required.issubset(fields) or len(fields) != len(set(fields))
                    or any(not field for field in fields)):
                raise ValueError(f'historical audit {name} requires unique nonempty headers')
            for values in reader:
                if len(values) != len(fields):
                    raise ValueError(f'historical audit {name} row width is inconsistent')
                yield dict(zip(fields, values))
    except (UnicodeError, csv.Error) as error:
        raise ValueError(f'historical audit {name} is malformed') from error


def _validate_history_dates(body, selected_dates):
    """The sealed date ledger must agree with every admitted summary result."""
    seen = set()
    for row in _history_csv_rows(body, 'dates.csv', {'run_date', 'status'}):
        run_date = row['run_date']
        if run_date not in selected_dates or run_date in seen:
            raise ValueError('historical audit dates.csv contains an unselected or duplicate date')
        if row['status'] != selected_dates[run_date]:
            raise ValueError('historical audit dates.csv status disagrees with selected summary')
        seen.add(run_date)
    if seen != set(selected_dates):
        raise ValueError('historical audit dates.csv omits selected dates')


def _admit_history_exports(stage, output):
    """Retain interrupted output; recovery uses a new immutable report directory."""
    targets = sorted(stage.iterdir())
    if any((output / path.name).exists() or (output / path.name).is_symlink() for path in targets):
        raise ValueError('historical report output already exists')
    admitted = []
    try:
        for path in targets:
            os.link(path, output / path.name)  # Same filesystem; never replace existing output.
            admitted.append(path.name)
    except OSError as error:
        # Path-based rollback could delete a replacement created by another writer.
        names = ', '.join(admitted) or 'none'
        raise OSError(f'historical report admission incomplete: {len(admitted)} files linked ({names}); '
                      'preserve this incomplete output and retry with a new output directory') from error


def _prepare_history_exports(output, source, summary, raw, exports, historical_banks, audited):
    """No report mutation: invalid later detail evidence discards only this stage."""
    row_counts = {'historical-banks.csv': write_csv(output / 'historical-banks.csv', historical_banks)}
    if 'details' in summary.get('assets_checked_per_date', []):
        from cdr_historical_parameters import rows as parameter_changes
        row_counts['historical-parameter-changes.csv.gz'] = write_csv(
            output / 'historical-parameter-changes.csv.gz', parameter_changes(source, summary))
        audited['parameter_changes_semantics'] = (
            'Every captured field at baseline and after calendar gaps, then changes on consecutive observation dates. '
            'Unchanged fields are present in the retained dated details. Missing product/date is not withdrawal, '
            'and no value is inferred for a missing calendar date. Effective legal dates remain unknown.')
    for name, target in [('dates.csv', 'historical-dates.csv'),
                         ('bank-product-dates.csv', 'historical-products.csv'),
                         ('summary.json', 'historical-audit.json')]:
        body = raw if name == 'summary.json' else exports[name]
        (output / target).write_bytes(body)
        audited['exports'][target] = {'bytes': len(body), 'sha256': digest(body)}
    return row_counts


def generate(root: Path, output: Path, history_audit: Path | None = None,
             metrics_doc: Path | None = None, metrics_code_base: str | None = None):
    root, output = root.resolve(), output.resolve()
    if root == output or root in output.parents or output in root.parents:
        raise ValueError('report output must be separate from all input evidence')
    if output.exists():
        raise ValueError('use a new immutable report directory')
    if history_audit:
        history_audit = history_audit.resolve()
        if history_audit == output or history_audit in output.parents or output in history_audit.parents:
            raise ValueError('report output must be separate from historical audit')
    manifest, payloads, evidence = read_bundle(root)
    products, rows, full = inventory_products(payloads['core'], payloads['details'])
    banks = bank_inventory(products, payloads['core'])
    fields = field_inventory(rows, payloads['details'])
    report = {'schema_version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(),
              'run_date': manifest['run_date'], 'source_manifest': manifest,
              'source_counts': manifest['counts'], 'published_counts': {
                  'products_in_details': len(payloads['details']['products']),
                  'products_with_rates': sum(p['published_rate_rows'] > 0 for p in products),
                  'rate_rows': len(rows), 'named_banks_in_public_inventory': len(banks),
                  **{group: sum(p[group + '_entries'] for p in products) for group in GROUPS}},
              'historical_coverage': date_coverage(root, manifest),
              'coverage': payloads['core'].get('coverage'), 'evidence': evidence,
              'fields': fields, 'banks': banks, 'products': products,
              'limitations': [
                  'Counts describe delivered CDR fields, not complete official product documents.',
                  'No document archive, complete clause inventory or executable terms coverage is present in the baseline.',
                  'Manifest source counts differ from shipped projections; all denominators are retained separately.',
                  'Absent fee or criterion means unreported, not zero or unrestricted.',
                  'Legacy historical population is not inferred from current banks/products.',
                  'App parser, native UI, Pi source integrity and each dated release require separate evidence.',
                  'CSV formula-like strings are prefixed with apostrophe; original values remain in JSON.',
              ]}
    output.mkdir(parents=True)
    columns = sorted({key for row in rows for key in row})
    report['export_row_counts'] = {
        'banks.csv': write_csv(output / 'banks.csv', banks),
        'products.csv': write_csv(output / 'products.csv', products),
        'rates.csv': write_csv(output / 'rates.csv', rows, columns),
        'fields.csv': write_csv(output / 'fields.csv', fields),
        'product-parameters.csv': write_csv(output / 'product-parameters.csv', detail_rows(full)),
        'historical-metrics.csv': write_csv(output / 'historical-metrics.csv', historical_rows(payloads)),
    }
    if history_audit:
        attach_history(report, history_audit, output)
    if metrics_doc:
        source_body = metrics_doc.read_bytes()
        body = source_body
        if metrics_code_base:
            if not re.fullmatch(r'https://github\.com/[\w.-]+/[\w.-]+/blob/[0-9a-f]{40}', metrics_code_base):
                raise ValueError('metrics code base requires an exact GitHub commit URL')
            body = re.sub(r'\]\(\.\./([^\s)]+)\)', lambda match: '](' + metrics_code_base + '/' + match[1] + ')',
                          source_body.decode('utf-8')).encode('utf-8')
        (output / 'reported-metrics.md').write_bytes(body)
        report['metrics_dictionary'] = {'file': 'reported-metrics.md', 'sha256': digest(body),
                                        'source_sha256': digest(source_body), 'code_base': metrics_code_base}
    (output / 'audit-evidence.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'product-data.json').write_text(json.dumps(full, ensure_ascii=False), encoding='utf-8')
    write_html(output / 'report.html', report, full)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--history-audit', type=Path)
    parser.add_argument('--metrics-doc', type=Path)
    parser.add_argument('--metrics-code-base', help='Exact GitHub commit URL for portable dictionary code links.')
    args = parser.parse_args()
    report = generate(args.bundle, args.output, args.history_audit, args.metrics_doc, args.metrics_code_base)
    print(json.dumps({'result': 'BASELINE_INVENTORY', 'published_counts': report['published_counts'],
                      'exports': report['export_row_counts'], 'output': str(args.output.resolve())}))


if __name__ == '__main__':
    main()
