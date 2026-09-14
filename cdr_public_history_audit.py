"""Audit every selected dated AR-app core without changing any publication.

The input dates index is pinned locally. No force publication, source migration,
forward-fill or rate-unit heuristic is used. Individual raw releases are retained.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from cdr_product_report import GROUPS, identity, write_csv
from cdr_report_io import decode_json
from cdr_history_validation import ordered_dates, manifest_shape, core_shape, details_shape, export_bindings
from cdr_terms.acquisition import FetchFailure, FetchPolicy, fetch_document

ROOT = 'https://github.com/yanniedog/AR-local/releases/download/'
MAX_COMPRESSED = 16 * 1024**2
MAX_PLAIN = 96 * 1024**2


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def fetch(url: str, maximum: int) -> bytes:
    """Only public GitHub release transport; bound every response and redirect."""
    hosts = {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
    result = fetch_document(url, policy=FetchPolicy(max_bytes=maximum, timeout_seconds=35,
                                                    allowed_hosts=frozenset(hosts)))
    if result['status'] != 'fetched':
        raise ValueError('public release did not return fresh bytes')
    return result['body']


def decode(body: bytes) -> dict:
    return decode_json(body, compressed=True, max_plain=MAX_PLAIN)


def read_cached(path: Path, maximum: int) -> bytes:
    """Apply transport bounds to disk snapshots, including growth after stat."""
    if path.stat().st_size > maximum:
        raise ValueError('cached asset exceeds byte limit')
    with path.open('rb') as handle:
        body = handle.read(maximum + 1)
    if len(body) > maximum:
        raise ValueError('cached asset exceeds byte limit')
    return body


def audit_date(run_date: str, head: dict | None, root: Path,
               cached_cores: Path | None = None, include_details: bool = False) -> tuple[dict, list]:
    result = {'run_date': run_date, 'status': 'FAIL', 'checked_at': datetime.now(timezone.utc).isoformat()}
    directory = root / run_date
    directory.mkdir()
    try:
        url = head['manifest_url'] if head else ROOT + 'app-payload-' + run_date + '/manifest.json'
        manifest_bytes = (read_cached(cached_cores / run_date / 'manifest.json', 1024**2)
                          if cached_cores else fetch(url, 1024**2))
        (directory / 'manifest.json').write_bytes(manifest_bytes)
        if head and sha(manifest_bytes) != head['manifest_sha256']:
            raise ValueError('selected manifest hash changed')
        manifest = json.loads(manifest_bytes)
        manifest_shape(manifest, run_date, details=include_details)
        if manifest['run_date'] != run_date:
            raise ValueError('dated manifest mismatch')
        if head and manifest.get('payload_revision', {}).get('bundle_sha256') != head['bundle_sha256']:
            raise ValueError('selected bundle mismatch')
        asset = manifest['files']['core']
        body = (read_cached(cached_cores / run_date / 'core.json.gz', MAX_COMPRESSED)
                if cached_cores else fetch(asset['url'], MAX_COMPRESSED))
        (directory / 'core.json.gz').write_bytes(body)
        if len(body) != asset['bytes'] or sha(body) != asset['sha256']:
            raise ValueError('dated core hash or length mismatch')
        core = decode(body)
        core_shape(core, run_date)
        if core['run_date'] != run_date or set(core['sections']) != {'Mortgage', 'Savings', 'TD'}:
            raise ValueError('dated core structure mismatch')
        rows, all_rates = [], defaultdict(list)
        for section, data in core['sections'].items():
            grouped = defaultdict(list)
            for rate in data['rates']:
                grouped[rate['product_key']].append(rate)
                all_rates[rate['product_key']].append(rate)
            for key, rates in grouped.items():
                rows.append({'run_date': run_date, 'provider': rates[0]['provider'],
                             'product_key': key, 'section': section, 'rate_rows': len(rates),
                             'zero_rate_rows': sum(str(r.get('rate')) in {'0', '0.0', '0.00'} for r in rates),
                             'missing_taxonomy_rows': sum(not r.get('taxonomy_path') for r in rates),
                             'core_sha256': sha(body),
                             'observation_status': 'published_observation; terms_not_verified'})
        if include_details:
            detail_asset = manifest['files']['details']
            cached_detail = cached_cores / run_date / 'details.json.gz' if cached_cores else None
            detail_bytes = (read_cached(cached_detail, MAX_COMPRESSED) if cached_detail and cached_detail.is_file()
                            else fetch(detail_asset['url'], MAX_COMPRESSED))
            (directory / 'details.json.gz').write_bytes(detail_bytes)
            if len(detail_bytes) != detail_asset['bytes'] or sha(detail_bytes) != detail_asset['sha256']:
                raise ValueError('dated details hash or length mismatch')
            details = decode(detail_bytes)
            details_shape(details, run_date, GROUPS)
            if details['run_date'] != run_date or not isinstance(details['products'], dict):
                raise ValueError('dated details structure mismatch')
            for key in sorted(set(details['products']) - set(all_rates)):
                rows.append({'run_date': run_date, 'provider': identity(key, [])['provider'],
                             'product_key': key, 'section': '', 'rate_rows': 0,
                             'zero_rate_rows': 0, 'missing_taxonomy_rows': 0,
                             'core_sha256': sha(body),
                             'observation_status': 'detail_only; no_published_rate; terms_not_verified'})
            for row in rows:
                detail = details['products'].get(row['product_key'])
                row.update(detail_present=detail is not None,
                           details_sha256=sha(detail_bytes),
                           detail_fields='|'.join(sorted(detail or {})),
                           **{group + '_entries': len((detail or {}).get(group, [])) for group in GROUPS})
            result.update(details_sha256=sha(detail_bytes),
                          products_in_details=len(details['products']),
                          products_without_rates=len(set(details['products']) - set(all_rates)),
                          **{group + '_entries': sum(len(d.get(group, [])) for d in details['products'].values())
                             for group in GROUPS})
        result.update(status='PASS', manifest_sha256=sha(manifest_bytes), core_sha256=sha(body),
                      manifest_url=url, revision=(head or {}).get('revision'),
                      generation_id=manifest.get('source_observation', {}).get('generation_id'),
                      providers=len({r['provider'] for r in rows}),
                      products=len({r['product_key'] for r in rows}),
                      rate_rows=sum(r['rate_rows'] for r in rows),
                      missing_taxonomy_rows=sum(r['missing_taxonomy_rows'] for r in rows),
                      zero_rate_rows=sum(r['zero_rate_rows'] for r in rows))
        return result, rows
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, FetchFailure) as error:
        # Exception classes preserve a useful disposition without signing URLs,
        # authentication headers or arbitrary remote error bodies in the report.
        result['reason'] = type(error).__name__
        if isinstance(error, ValueError):
            result['reason_detail'] = str(error)
        if isinstance(error, FetchFailure):
            result['http_status'] = error.http_status
            result['reason_detail'] = error.code
        return result, []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dates-index', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cached-cores', type=Path,
                        help='Reuse a prior pinned core audit; its index must match exactly.')
    parser.add_argument('--include-details', action='store_true')
    args = parser.parse_args()
    source = args.dates_index.resolve()
    output = args.output.resolve()
    if (output.exists() or output == source.parent or output in source.parents
            or source.parent in output.parents):
        raise ValueError('new separate historical audit directory required')
    raw = source.read_bytes()
    if args.cached_cores:
        cached = args.cached_cores.resolve()
        if cached == output or cached in output.parents or output in cached.parents:
            raise ValueError('audit output must be separate from cached evidence')
        if read_cached(cached / 'dates-index.json', 1024**2) != raw:
            raise ValueError('cached index differs from selected index')
    index = json.loads(raw)
    dates = ordered_dates(index)
    output.mkdir(parents=True)
    (output / 'dates-index.json').write_bytes(raw)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = executor.map(lambda d: audit_date(d, index.get('revision_heads', {}).get(d),
                              output, args.cached_cores, args.include_details), dates)
        audits, products = [], []
        with (output / 'date-results.jsonl').open('x', encoding='utf-8') as log:
            for result, rows in results:
                audits.append(result)
                products.extend(rows)
                log.write(json.dumps(result, sort_keys=True) + '\n')
                log.flush()
                print(json.dumps({k: result[k] for k in ('run_date', 'status')}), flush=True)
    columns = sorted({k for r in audits for k in r})
    write_csv(output / 'dates.csv', audits, columns)
    write_csv(output / 'bank-product-dates.csv', products)
    summary = {'schema_version': 1, 'index_sha256': sha(raw), 'dates_checked': len(audits),
               'exports': export_bindings(output),
               'dates_passed': sum(r['status'] == 'PASS' for r in audits),
               'product_section_days': len(products), 'results': audits,
               'assets_checked_per_date': ['manifest', 'core', 'details'] if args.include_details else ['manifest', 'core'],
               'limitations': ['Dates index population only; missing calendar dates remain separate gaps.',
                   'Product absence is not proven withdrawal or failed collection.',
                   'Hash/parser verification does not prove source accuracy or full terms coverage.',
                   'Legacy manifests without revision heads are identified by bytes retrieved at audit time.']}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('dates_checked', 'dates_passed', 'product_section_days')}))
    return 0 if summary['dates_passed'] == len(audits) else 1


if __name__ == '__main__':
    raise SystemExit(main())
