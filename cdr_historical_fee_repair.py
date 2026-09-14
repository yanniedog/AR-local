"""Prepare additive fee repairs from matching retained same-day raw evidence.

Never publishes, rewrites source exports, changes rate bytes, or removes an old
fee. Conflicting identities/content are enumerated instead of guessed. The
output is a candidate requiring revision publication and independent acceptance.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app_payload_details import _fee_items
from cdr_clean_export import clean_value
from cdr_product_report import write_csv
from cdr_public_history_audit import decode


def sha(body):
    return hashlib.sha256(body).hexdigest()


def enrich_fee(old: dict, raw: dict) -> tuple[dict, str | None]:
    enriched = _fee_items({'fees': [raw]})[0]
    # Every existing disclosure must agree, including cadence and exact text.
    comparable = clean_value(enriched)
    conflicts = {key for key, value in old.items() if key not in comparable or comparable[key] != value}
    if (conflicts == {'value'} and 'value' not in enriched
            and enriched.get('amountStatus') == 'variable'
            and exact_zero(old['value']) and exact_zero(raw.get('amount'))):
        # Reviewed variable_zero_placeholder_v1: the authoritative source says
        # VARIABLE with an exact zero placeholder. Keep its raw amount, but drop
        # only the misleading legacy display value. All other old fields agree.
        retained = {key: value for key, value in old.items() if key != 'value'}
        return {**retained, **{key: value for key, value in enriched.items() if key not in retained}}, None
    if conflicts:
        return old, 'published_fee_conflicts_with_retained_projection'
    additions = {key: value for key, value in enriched.items() if key not in old}
    return {**old, **additions}, None


def exact_zero(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return False
    try:
        number = Decimal(str(value))
        return number.is_finite() and number == 0
    except InvalidOperation:
        return False


def retained_record(product: dict, run: Path) -> tuple[dict, dict]:
    path = Path(product['source_file']).resolve()
    banks = (run / 'banks').resolve()
    if banks not in path.parents or path.is_symlink() or not path.is_file():
        raise ValueError('retained_raw_path_unavailable_or_outside_run')
    body = path.read_bytes()
    record = json.loads(body)['data']
    for source, target in [('productId', 'product_id'), ('name', 'product_name'),
                           ('productCategory', 'category'), ('lastUpdated', 'last_updated')]:
        if record.get(source, '') != product.get(target, ''):
            raise ValueError('retained_raw_identity_differs_from_export')
    exported = json.loads(product['details_json'])
    # Match the raw fee array to the retained export with a recursive subset:
    # cleaning historically dropped additionalInfoUri, not the captured value.
    if not subset(exported.get('fees', []), clean_value(record.get('fees', []))):
        raise ValueError('retained_export_fee_evidence_conflict')
    evidence = {'relative_raw_path': path.relative_to(run).as_posix(),
                'raw_sha256': sha(body), 'raw_bytes': len(body)}
    return record, evidence


def subset(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and subset(value, actual[key])
                                               for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            subset(left, right) for left, right in zip(expected, actual))
    return type(expected) is type(actual) and expected == actual


def prepare(run: Path, released: Path, output: Path) -> dict:
    run, released, output = run.resolve(), released.resolve(), output.resolve()
    if output.exists() or any(output == root or root in output.parents or output in root.parents
                              for root in (run, released)):
        raise ValueError('new separate candidate directory required')
    source_path = run / '_exports' / f'banks-{run.name}.json'
    source_bytes = source_path.read_bytes()
    source = json.loads(source_bytes)
    manifest_bytes = (released / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    if source['run_date'] != run.name or manifest['run_date'] != run.name:
        raise ValueError('retained and published observation dates differ')
    inputs = {'manifest.json': manifest_bytes}
    for kind in ('core', 'details'):
        body = (released / f'{kind}.json.gz').read_bytes()
        expected = manifest['files'][kind]
        if sha(body) != expected['sha256'] or len(body) != expected['bytes']:
            raise ValueError('published input asset hash mismatch')
        inputs[f'{kind}.json.gz'] = body
    core, original = decode(inputs['core.json.gz']), decode(inputs['details.json.gz'])
    if any(payload.get('run_date') != run.name or payload.get('schema_version') != 1
           for payload in (core, original)):
        raise ValueError('published body date or schema differs from manifest')
    if not isinstance(original.get('products'), dict) or set(core.get('sections', {})) != {'Mortgage', 'Savings', 'TD'}:
        raise ValueError('published body structure invalid')
    candidate = copy.deepcopy(original)
    by_key = defaultdict(list)
    for product in source['products']:
        by_key[product['product_key']].append(product)
    changes, gaps, evidence = [], [], []
    for key, detail in original['products'].items():
        if len(by_key[key]) != 1:
            gaps.append({'product_key': key, 'reason': 'retained_product_missing_or_ambiguous'})
            continue
        try:
            record, proof = retained_record(by_key[key][0], run)
        except (OSError, ValueError, KeyError) as error:
            gaps.append({'product_key': key, 'reason': str(error) if isinstance(error, ValueError)
                         else 'retained_raw_record_unavailable'})
            continue
        evidence.append({'product_key': key, **proof})
        old_fees, raw_fees = detail.get('fees', []), record.get('fees', [])
        if len(old_fees) != len(raw_fees):
            gaps.append({'product_key': key, 'reason': 'fee_array_length_differs'})
            continue
        for index, (old, raw) in enumerate(zip(old_fees, raw_fees)):
            new, conflict = enrich_fee(old, raw)
            if conflict:
                gaps.append({'product_key': key, 'fee_index': index, 'reason': conflict})
            elif new != old:
                candidate['products'][key]['fees'][index] = new
                changes.append({'product_key': key, 'fee_index': index,
                                'source_pointer': f'/data/fees/{index}',
                                'raw_sha256': proof['raw_sha256'], 'before': old, 'after': new,
                                'change_kind': 'extraction_correction', 'legal_amendment': False,
                                'rule_id': 'variable_zero_placeholder_v1' if 'value' in old and 'value' not in new
                                           else 'missing_structured_fee_fields_v1',
                                'removed_fields': sorted(set(old) - set(new))})
    # Recheck all retained inputs before writing the derived candidate.
    if sha(source_path.read_bytes()) != sha(source_bytes):
        raise ValueError('retained export changed during preparation')
    for proof in evidence:
        if sha((run / proof['relative_raw_path']).read_bytes()) != proof['raw_sha256']:
            raise ValueError('retained raw source changed during preparation')
    candidate_bytes = gzip.compress(json.dumps(candidate, ensure_ascii=False,
                                     separators=(',', ':')).encode('utf-8'), mtime=0)
    receipt = {'schema_version': 1, 'result': 'CANDIDATE_ONLY', 'publication': 'NOT_ATTEMPTED',
               'observation_date': run.name, 'corrected_at': datetime.now(timezone.utc).isoformat(),
               'source_export_sha256': sha(source_bytes), 'source_manifest_sha256': sha(manifest_bytes),
               'core_sha256_unchanged': sha(inputs['core.json.gz']),
               'original_details_sha256': sha(inputs['details.json.gz']),
               'candidate_details_sha256': sha(candidate_bytes),
               'candidate_details_bytes': len(candidate_bytes),
               'products_with_additions': len({change['product_key'] for change in changes}),
               'fees_with_additions': len(changes), 'unresolved_records': len(gaps),
               'variable_zero_placeholders_corrected': sum(change['rule_id'] == 'variable_zero_placeholder_v1'
                                                           for change in changes),
               'retained_raw_records_verified': len(evidence),
               'limitations': ['Same-day retained evidence only; no current document backdating.',
                   'Additive field repair does not certify complete legal terms or pricing.',
                   'Conflicting or unavailable records remain unchanged.',
                   'Independent review, higher immutable revision and consumer acceptance required.']}
    output.mkdir(parents=True)
    (output / 'core.json.gz').write_bytes(inputs['core.json.gz'])
    (output / 'details-candidate.json.gz').write_bytes(candidate_bytes)
    for name, value in [('receipt.json', receipt), ('changes.json', changes),
                         ('unresolved.json', gaps), ('retained-evidence.json', evidence)]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    write_csv(output / 'changes.csv', changes)
    write_csv(output / 'unresolved.csv', gaps, ['product_key', 'fee_index', 'reason'])
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retained-run', type=Path, required=True)
    parser.add_argument('--released-audit-date', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.retained_run, args.released_audit_date, args.output)))


if __name__ == '__main__':
    main()
