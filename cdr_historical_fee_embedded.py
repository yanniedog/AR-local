"""Build one unpublished fee candidate from the approved May13 embedded export.

No raw-response, archive, database, network or publication adapter is provided.
"""
from __future__ import annotations

import argparse
import copy
import os
import shutil
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app_payload_details import _fee_items
from cdr_historical_fee_admission import DATE, load_inputs
from cdr_historical_fee_exact import canonical_sha, decode, encode, exact, gzip_bytes, sha
from cdr_historical_fee_membership import account, fee_array_binding, product_evidence

POLICY = 'may13-embedded-export-fees-v1'
VARIABLE_ZERO_RULE = 'variable_zero_placeholder_v3'
# Earlier rules remain named solely for structural restoration of old receipts.
# New literal and normalized corrections both require proven present bounds.
VARIABLE_ZERO_REVIEW_RULES = frozenset(('variable_zero_placeholder_v1', 'variable_zero_placeholder_v2', VARIABLE_ZERO_RULE))
PROJECTION_SOURCES = {
    # Optional rate disclosures changed the module; the fee projection and all
    # three helpers remain AST-identical to the previously reviewed version.
    'app_payload_details.py': '6963791b2d12805d74b963124a264c4bb33075dc78a4f283f01c0a27c1650126',
    'app_payload_common.py': 'cce4a7b19b4f86c7b52cde122b8a86d68c47b29dc1eb939fc7673a8225cd942d',
}
# Additive reviewed code identity: display metadata changes no fee helper.
# Preserve the earlier pin for retained receipt interpretation.
CURRENT_PROJECTION_SOURCES = {
    **PROJECTION_SOURCES,
    'app_payload_details.py': '533ddce96c8e4bbdcaa1b011343e5643f8ea40636ba72ef79f36d82d29bc3510',
}
DIRECT_FIELDS = frozenset(('amount', 'currency', 'additionalValue', 'balanceRate', 'transactionRate',
                          'accruedRate', 'accrualFrequency', 'feeCap', 'feeCapPeriod', 'feeMethodUType',
                          'fixedAmount', 'variable', 'rateBased', 'discounts'))
OUTPUT_FIELDS = DIRECT_FIELDS | {'label', 'name', 'value', 'info', 'amountStatus'}
SOURCE_FIELDS = DIRECT_FIELDS | {'feeType', 'name', 'additionalInfo'}


def verify_projection():
    observed = {}
    for name, expected in PROJECTION_SOURCES.items():
        actual = sha(Path(__file__).with_name(name).read_bytes().replace(b'\r\n', b'\n'))
        if actual not in {expected, CURRENT_PROJECTION_SOURCES[name]}:
            raise ValueError('fee_projection_changed_requires_review')
        observed[name] = actual
    return observed


def number(value):
    if type(value) is bool or not isinstance(value, (str, int, Decimal)):
        return None
    try:
        parsed = Decimal(value)
        return parsed if parsed.is_finite() else None
    except InvalidOperation:
        return None


def _conflicting_lower_bound(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in {'minimumamount', 'minimumvalue', 'minamount', 'lowerbound', 'loweramount'}:
                bound = number(child)
                if bound is None or bound != 0:
                    return True
            if _conflicting_lower_bound(child):
                return True
    elif isinstance(value, list):
        return any(_conflicting_lower_bound(item) for item in value)
    return False


def enrich(old, fee):
    """Retain old fields exactly; only the reviewed variable-zero deletion exists."""
    projected = _fee_items({'fees': [fee]})[0]
    if not set(projected) <= OUTPUT_FIELDS:
        raise ValueError('projection_contains_unreviewed_field')
    # The exact writer rejects any accidental float introduced by a helper.
    encode(projected)
    conflicts = {key for key, value in old.items() if key not in projected or not exact(value, projected[key])}
    rule = 'missing_structured_fee_fields_v1'
    retained = dict(old)
    if (conflicts == {'value'} and 'value' not in projected and projected.get('amountStatus') == 'variable'
            and number(old['value']) == 0 and number(fee.get('amount')) == 0
            and not _conflicting_lower_bound(fee)):
        retained.pop('value')
        conflicts.clear()
        rule = VARIABLE_ZERO_RULE
    if conflicts:
        return old, {'status': 'WITHHELD', 'reason': 'published_fee_conflicts_with_retained_projection',
                     'conflicting_fields': sorted(conflicts)}
    additions = {key: value for key, value in projected.items() if key not in retained}
    result = {**retained, **additions}
    for field in DIRECT_FIELDS & additions.keys():
        if field not in fee or not exact(result[field], fee[field]):
            raise ValueError('direct_source_field_changed')
    return result, {'status': 'UNCHANGED' if exact(result, old) else 'REPAIRED', 'rule_id': rule,
                    'added_fields': sorted(additions), 'removed_fields': sorted(set(old) - set(result))}


def field_proofs(before, after, fee, index):
    proofs = {}
    for field in sorted(set(after) - set(before)):
        if field in DIRECT_FIELDS:
            proofs[field] = {'kind': 'direct', 'embedded_pointer': f'/fees/{index}/{field}',
                             'source_value_canonical_sha256': canonical_sha(fee[field])}
        elif field == 'amountStatus':
            inputs = {key: {'present': key in fee, 'value': fee.get(key)} for key in (
                'feeMethodUType', 'feeType', 'balanceRate', 'transactionRate', 'accruedRate', 'fixedAmount', 'amount')}
            proofs[field] = {'kind': 'derived', 'rule_id': 'pinned_fee_amount_status_v1', 'inputs': inputs}
        elif field == 'value':
            # Match the helper's source priority without making a fabricated pointer.
            from app_payload_details import _present
            path = 'additionalValue' if _present(fee.get('additionalValue')) else 'amount' if _present(fee.get('amount')) else 'fixedAmount/amount'
            proofs[field] = {'kind': 'derived', 'rule_id': 'pinned_legacy_fee_value_v1',
                             'input_embedded_pointer': f'/fees/{index}/{path}'}
        else:
            raise ValueError('unreviewed_legacy_display_addition')
    return proofs


def transform(source, core, original, *, deadline=None, checkpoint=None):
    products, flat, product_rows, rate_rows, withheld = account(source, core, original, checkpoint=checkpoint)
    candidate = copy.deepcopy(original)
    fees, changes, bindings, seen_flat = [], [], [], set()
    banks = defaultdict(Counter)
    for entry in product_rows:
        if checkpoint is not None:
            checkpoint()
        if deadline is not None and time.monotonic() >= deadline:
            raise ValueError('candidate_deadline_exceeded')
        key = entry['product_key']
        entry['membership_status'] = entry['status']
        detail = original['products'].get(key)
        provider = products[key][1]['provider'] if key in products else None
        reasons = withheld.get(key, [])
        if key in products:
            index, product, raw = products[key]
            binding = {'product_key': key, **product_evidence(index, product, raw)}
            bindings.append(binding)
            reason, flat_indices = fee_array_binding(key, product, raw, detail, flat, checkpoint=checkpoint)
            reasons = reasons or ([reason] if reason else [])
            if not reasons:
                # Value-only legacy projection differences are scoped conflicts.
                # A changed label/name/info leaves array order unproved, so no
                # fee in that product can donate fields by position.
                for old, fee in zip(detail['fees'], raw['fees']):
                    if checkpoint is not None:
                        checkpoint()
                    projected = _fee_items({'fees': [fee]})[0]
                    if any((field in old) != (field in projected) or not exact(old.get(field), projected.get(field))
                           for field in ('label', 'name', 'info')):
                        reasons = ['public_fee_array_identity_or_order_unproved']
                        break
        else:
            raw, flat_indices = {}, []
        old_fees = detail.get('fees') if isinstance(detail, dict) else None
        source_fees = raw.get('fees')
        entry['public_fees_present'] = isinstance(detail, dict) and 'fees' in detail
        entry['source_fees_present'] = 'fees' in raw
        entry['public_fee_count'] = len(old_fees) if isinstance(old_fees, list) else None
        entry['source_fee_count'] = len(source_fees) if isinstance(source_fees, list) else None
        if reasons:
            entry['status'], entry['reasons'] = 'WITHHELD', sorted(set(reasons))
        if not isinstance(old_fees, list):
            fees.append({'product_key': key, 'status': 'ARRAY_NOT_COMPARABLE', 'fee_index': None,
                         'reason': 'public_fee_array_missing_null_or_wrong_type',
                         'public_fees_present': isinstance(detail, dict) and 'fees' in detail,
                         'public_fees_value': old_fees})
            continue
        if not old_fees:
            fees.append({'product_key': key, 'status': 'EMPTY_ARRAY', 'fee_index': None,
                         'source_fees_present': 'fees' in raw, 'reasons': reasons})
        for index, old in enumerate(old_fees):
            if checkpoint is not None:
                checkpoint()
            row = {'product_key': key, 'fee_index': index, 'public_fee_canonical_sha256': canonical_sha(old)}
            if reasons:
                row.update(status='WITHHELD', reasons=reasons)
            else:
                fee = source_fees[index]
                flat_index = flat_indices[index]
                seen_flat.add(flat_index)
                new, disposition = enrich(old, fee)
                row.update(disposition, embedded_fee_index=index, flattened_fee_index=flat_index,
                           embedded_fee_canonical_sha256=canonical_sha(fee),
                           unsupported_consumer_fields=sorted(set(fee) - SOURCE_FIELDS))
                if disposition['status'] == 'REPAIRED':
                    candidate['products'][key]['fees'][index] = new
                    changes.append({**row, 'embedded_string_pointer': binding['embedded_string_pointer'],
                                    'embedded_string_utf8_sha256': binding['embedded_string_utf8_sha256'],
                                    'embedded_fee_pointer': f'/fees/{index}', 'before': old, 'after': new,
                                    'field_sources': field_proofs(old, new, fee, index),
                                    'change_kind': 'extraction_correction', 'legal_amendment': False})
            fees.append(row)
            banks[provider or 'UNRESOLVED_PROVIDER'][row['status']] += 1
    for index, row in enumerate(source['fees']):
        if index not in seen_flat:
            fees.append({'status': 'SOURCE_ONLY_OR_WITHHELD', 'source_flattened_fee_index': index,
                         'product_key': row['product_key'], 'source_item_index': row['item_index'],
                         'reason': 'not_donated_to_candidate'})
    verify_changes(original, candidate, changes, checkpoint=checkpoint)
    return candidate, {'products': product_rows, 'rates': rate_rows, 'fees': fees,
                       'changes': changes, 'bindings': bindings, 'banks': dict(banks)}


def verify_changes(original, candidate, changes, *, checkpoint=None):
    restored = copy.deepcopy(candidate)
    seen = set()
    for change in changes:
        if checkpoint is not None:
            checkpoint()
        key, index = change['product_key'], change['fee_index']
        if (key, index) in seen:
            raise ValueError('duplicate_fee_change')
        seen.add((key, index))
        old, new = original['products'][key]['fees'][index], candidate['products'][key]['fees'][index]
        removed = set(old) - set(new)
        if removed and (removed != {'value'} or change['rule_id'] not in VARIABLE_ZERO_REVIEW_RULES):
            raise ValueError('unapproved_fee_field_deletion')
        if not set(new) - set(old) <= OUTPUT_FIELDS or any(not exact(value, new[field]) for field, value in old.items() if field not in removed):
            raise ValueError('existing_fee_value_type_or_presence_changed')
        if not exact(change['before'], old) or not exact(change['after'], new):
            raise ValueError('change_receipt_does_not_bind_values')
        restored['products'][key]['fees'][index] = copy.deepcopy(old)
    if not exact(restored, original):
        raise ValueError('non_fee_value_order_or_multiplicity_changed')


def _write(path, body):
    with path.open('xb') as stream:
        if stream.write(body) != len(body):
            raise OSError('candidate_short_write')
        stream.flush()
        os.fsync(stream.fileno())


def prepare(source, recovery, anchor, parent, parent_review, output):
    paths = [Path(value).absolute() for value in (source, recovery, anchor, parent, parent_review)]
    output = Path(output).resolve()
    resolved = [path.resolve() for path in paths]
    if output.exists() or any(output == path or output in path.parents or path in output.parents for path in resolved):
        raise ValueError('new_separate_candidate_directory_required')
    if not output.parent.is_dir() or shutil.disk_usage(output.parent).free < 3 * 1024**3:
        raise ValueError('candidate_requires_existing_parent_and_3gib_free_space')
    started = time.monotonic()
    projection_sources = verify_projection()
    loaded = load_inputs(*paths)
    candidate, audit = transform(loaded['source'], loaded['anchor_core'], loaded['details'], deadline=started + 600)
    candidate_json = encode(candidate)
    if len(candidate_json) > 96 * 1024**2 or not exact(decode(candidate_json), candidate):
        raise ValueError('candidate_size_or_exact_json_roundtrip_failed')
    payloads = {'core.json.gz': loaded['core_bytes'], 'details-candidate.json.gz': gzip_bytes(candidate_json)}
    for key in ('products', 'rates', 'fees', 'changes', 'bindings'):
        payloads[key + '.jsonl'] = b''.join(encode(row) + b'\n' for row in audit[key])
    payloads['bank-dispositions.json'] = encode(audit['banks'])
    if sum(map(len, payloads.values())) > 512 * 1024**2 or time.monotonic() - started > 600:
        raise ValueError('candidate_output_or_time_bound_exceeded')
    loaded['inputs'].recheck()
    counts = dict(Counter(row['status'] for row in audit['fees'] if row.get('fee_index') is not None))
    arrays = dict(Counter(row['status'] for row in audit['fees'] if 'fee_index' in row and row['fee_index'] is None))
    source_only = sum('source_flattened_fee_index' in row for row in audit['fees'])
    admission = {'schema_version': 1, 'contract': 'embedded_export_fee_admission_v1',
                 'evidence_kind': 'embedded_export_details_json', 'observation_date': DATE,
                 'source_generation_time': loaded['source_generation_time'], 'source_observed_at': None,
                 'created_at': datetime.now(timezone.utc).isoformat(), 'policy_version': POLICY,
                 'container': loaded['container'], 'inputs': loaded['inputs'].records,
                 'parent_kind': 'UNPUBLISHED_TAXONOMY_CANDIDATE', 'parent_lineage': loaded['parent_lineage'],
                 'projection_source_sha256_lf': projection_sources,
                 'adapter_source_sha256_lf': {name: sha(Path(__file__).with_name(name).read_bytes().replace(b'\r\n', b'\n'))
                     for name in ('cdr_historical_fee_exact.py', 'cdr_historical_fee_admission.py',
                                  'cdr_historical_fee_membership.py', 'cdr_historical_fee_embedded.py')},
                 'untouched_optional_assets': {key: value for key, value in loaded['anchor_manifest']['files'].items()
                                              if key not in ('core', 'details')},
                 'membership': {'products': len(audit['products']), 'rates': len(audit['rates']),
                                'fee_dispositions': counts, 'array_dispositions': arrays,
                                'public_fee_objects': sum(row['public_fee_count'] or 0 for row in audit['products']),
                                'source_flattened_fee_rows': len(loaded['source']['fees']),
                                'source_only_or_withheld_rows': source_only,
                                'membership_canonical_sha256': canonical_sha(audit['products'])},
                 'publication': 'NOT_ATTEMPTED', 'calculation_completeness': 'UNKNOWN',
                 'customer_eligibility': 'UNKNOWN', 'full_fee_applicability': 'UNKNOWN'}
    identity = {key: value for key, value in admission.items() if key not in ('created_at', 'inputs')}
    identity['input_hashes'] = {key: value['sha256'] for key, value in admission['inputs'].items()}
    identity['output_hashes'] = {key: sha(body) for key, body in payloads.items()}
    admission['admission_id'] = canonical_sha(identity)
    from jsonschema import Draft202012Validator, FormatChecker
    schema = decode((Path(__file__).parent / 'contracts/historical-fees/embedded-export-v1.schema.json').read_bytes())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(admission)
    payloads['admission.json'] = encode(admission)
    receipt = {'schema_version': 1, 'result': 'CANDIDATE_SEALED_UNREVIEWED', 'publication': 'NOT_ATTEMPTED',
               'observation_date': DATE, 'admission_id': admission['admission_id'],
               'admission_sha256': sha(payloads['admission.json']), 'fee_dispositions': counts,
               'array_dispositions': arrays, 'source_only_or_withheld_rows': source_only,
               'fee_rules': dict(Counter(row['rule_id'] for row in audit['changes'])),
               'preexisting_numeric_rate_variants_preserved': sum(row.get('preexisting_numeric_rate_variant', False) for row in audit['rates']),
               'parent_core_bytes_unchanged': True, 'parent_lineage': loaded['parent_lineage'],
               'files': {name: {'sha256': sha(body), 'bytes': len(body)} for name, body in payloads.items()},
               'required_next': ['Independent reconstruction', 'Higher immutable revision', 'Consumer/native acceptance',
                                 'Separate controlled publication approval'],
               'limitations': ['Embedded export evidence is not an original HTTP capture.',
                               'Fields and conditions remain unknown unless explicitly evidenced.',
                               'No full terms, legal applicability, fee total or eligibility claim.',
                               'Drive writes prohibited; live Pi hold installation unverified.']}
    output.mkdir()  # Exclusive directory claim; incomplete outputs never receive a seal.
    for name, body in payloads.items():
        _write(output / name, body)
        if sha((output / name).read_bytes()) != sha(body):
            raise ValueError('candidate_write_verification_failed')
    loaded['inputs'].recheck()
    _write(output / 'receipt.json', encode(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'recovery', 'anchor', 'parent', 'parent-review', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    print(encode(prepare(args.source, args.recovery, args.anchor, args.parent, args.parent_review, args.output)).decode())


if __name__ == '__main__':
    main()
