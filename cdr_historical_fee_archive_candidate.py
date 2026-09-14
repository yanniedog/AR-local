"""One private May22 candidate; no publication or multi-date execution path."""
from __future__ import annotations

import argparse
import shutil
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from cdr_historical_fee_archive import Budget, MIB, private_path, read_verified, safe_path, seal_exclusive, write_exclusive
from cdr_historical_fee_archive_admission import DATE, DESIGN_SHA, POLICY, PINS, SOURCE, load, recheck_inputs
from cdr_historical_fee_embedded import PROJECTION_SOURCES, transform, verify_projection
from cdr_historical_fee_exact import canonical_sha, decode, encode, exact, gzip_bytes, sha

SOURCES = ('cdr_historical_fee_archive.py', 'cdr_historical_fee_archive_admission.py',
           'cdr_historical_fee_archive_candidate.py', 'cdr_historical_fee_membership.py',
           'cdr_historical_fee_embedded.py', 'cdr_historical_fee_exact.py')


def separate_output(output, roots):
    output = private_path(output)
    for root in roots:
        root = safe_path(root, directory=True) if Path(root).exists() else private_path(root)
        if output == root or output in root.parents or root in output.parents:
            raise ValueError('new_separate_candidate_directory_required')
    if output.exists():
        raise ValueError('candidate_output_collision')
    if shutil.disk_usage(output.parent).free < 3 * 1024**3:
        raise ValueError('candidate_requires_3gib_free_space')
    return output


def validate_admission(admission):
    from jsonschema import Draft202012Validator, FormatChecker
    path = Path(__file__).parent / 'contracts/historical-fees/archive-export-v1.schema.json'
    Draft202012Validator(decode(path.read_bytes()), format_checker=FormatChecker()).validate(admission)


def _payloads(loaded, budget):
    candidate, audit = transform(loaded['source'], loaded['core'], loaded['details'],
                                deadline=budget.deadline, checkpoint=budget.check)
    budget.check()
    body = encode(candidate)
    if len(body) > 96 * MIB or not exact(decode(body), candidate):
        raise ValueError('candidate_details_bound_or_roundtrip')
    budget.check()
    payloads = {'core.json.gz': loaded['core_bytes'], 'details-candidate.json.gz': gzip_bytes(body)}
    for key in ('products', 'rates', 'fees', 'changes', 'bindings'):
        lines, size = [], 0
        for row in audit[key]:
            budget.check()
            line = encode(row) + b'\n'
            size += len(line)
            if size + sum(map(len, payloads.values())) > 512 * MIB:
                raise ValueError('candidate_total_output_bound')
            lines.append(line)
        payloads[key + '.jsonl'] = b''.join(lines)
    payloads['bank-dispositions.json'] = encode(audit['banks'])
    budget.check()
    return payloads, audit


def _admission(loaded, audit, payloads):
    counts = dict(Counter(row['status'] for row in audit['fees'] if row.get('fee_index') is not None))
    arrays = dict(Counter(row['status'] for row in audit['fees'] if 'fee_index' in row and row['fee_index'] is None))
    admission = {
        'schema_version': 1, 'contract': 'archive_export_fee_admission_v1', 'policy_version': POLICY,
        'evidence_kind': 'verified_observation_archive_member', 'observation_date': DATE,
        'approved_design_sha256': DESIGN_SHA, 'created_at': datetime.now(timezone.utc).isoformat(),
        'container': loaded['container'], 'inputs': loaded['inputs'], 'generation': loaded['generation'],
        'parent_kind': 'original_public_anchor', 'core_bytes_preserved': True,
        'untouched_optional_assets': {key: value for key, value in loaded['manifest']['files'].items() if key not in ('core', 'details')},
        'projection_source_sha256_lf': PROJECTION_SOURCES,
        'adapter_source_sha256_lf': {name: sha(Path(__file__).with_name(name).read_bytes().replace(b'\r\n', b'\n')) for name in SOURCES},
        'membership': {'products': len(audit['products']), 'rates': len(audit['rates']), 'fee_dispositions': counts,
                       'array_dispositions': arrays, 'public_fee_objects': sum(row['public_fee_count'] or 0 for row in audit['products']),
                       'source_flattened_fee_rows': len(loaded['source']['fees']),
                       'source_only_or_withheld_rows': sum('source_flattened_fee_index' in row for row in audit['fees']),
                       'membership_canonical_sha256': canonical_sha(audit['products'])},
        'output_files': {name: {'bytes': len(body), 'sha256': sha(body)} for name, body in payloads.items()},
        'publication': 'NOT_ATTEMPTED', 'calculation_completeness': 'UNKNOWN', 'customer_eligibility': 'UNKNOWN',
        'full_fee_applicability': 'UNKNOWN', 'source_http_capture': 'NOT_SUPPLIED',
    }
    admission['admission_id'] = canonical_sha({key: value for key, value in admission.items() if key != 'created_at'})
    validate_admission(admission)
    return admission


def prepare(archive_dir, anchor_dir, cache, output):
    """Requires the reviewed exact retained files; unsupported parents are refused."""
    budget = Budget()
    archive_dir, anchor_dir = safe_path(archive_dir, directory=True), safe_path(anchor_dir, directory=True)
    cache = private_path(cache)
    output = separate_output(output, (archive_dir, anchor_dir, cache))
    if shutil.disk_usage(cache.parent).free < 3 * 1024**3:
        raise ValueError('cache_requires_3gib_free_space')
    # Cache must not be placed inside either immutable source tree.
    for root in (archive_dir, anchor_dir):
        root, target = Path(root).absolute(), cache
        if root == target or root in target.parents or target in root.parents:
            raise ValueError('cache_must_be_separate_from_immutable_inputs')
    verify_projection()
    output.mkdir()
    plan = {'status': 'LISTED', 'observation_date': DATE, 'policy_version': POLICY, 'design_sha256': DESIGN_SHA,
            'archive': PINS['observation.tar.zst'], 'source': SOURCE, 'publication': 'NOT_ATTEMPTED'}
    write_exclusive(output / '01-listed.json', encode(plan), budget)
    try:
        loaded = load(archive_dir, anchor_dir, cache, budget)
        write_exclusive(output / '02-member-verified.json', encode({'status': 'MEMBER_VERIFIED', 'container': loaded['container']}), budget)
        payloads, audit = _payloads(loaded, budget)
        write_exclusive(output / '03-membership-accounted.json', encode({'status': 'MEMBERSHIP_ACCOUNTED',
                        'products_sha256': canonical_sha(audit['products']), 'products': len(audit['products'])}), budget)
        admission = _admission(loaded, audit, payloads)
        payloads['admission.json'] = encode(admission)
        for name, body in payloads.items():
            write_exclusive(output / name, body, budget)
            read_verified(output / name, {'bytes': len(body), 'sha256': sha(body)}, budget, limit=512 * MIB, capture=False)
        recheck_inputs(loaded, budget)
        receipt = {'schema_version': 1, 'result': 'CANDIDATE_SEALED_UNREVIEWED', 'observation_date': DATE,
                   'publication': 'NOT_ATTEMPTED', 'admission_id': admission['admission_id'],
                   'admission_sha256': sha(payloads['admission.json']),
                   'files': {name: {'bytes': len(body), 'sha256': sha(body)} for name, body in payloads.items()},
                   'resources': {'elapsed_seconds_before_seal': str(time.monotonic() - budget.started), 'counters_before_seal': dict(budget.counts)},
                   'required_next': ['Independent reconstruction', 'Immutable revision review', 'Separate publication gates'],
                   'limitations': ['Embedded export is not HTTP capture.', 'Legal effective dates and fee applicability remain unknown.',
                                   'No customer eligibility or complete cost claim.', 'Original public anchor only; no unreviewed parent chain.']}
        seal_exclusive(output / 'receipt.json', encode(receipt), budget)
        return receipt
    except Exception as exc:
        # Exhausted operations do not receive fresh budget merely to write a status.
        if time.monotonic() < budget.deadline and budget.counts.get('output', 0) < 512 * MIB - 4096:
            write_exclusive(output / 'withheld.json', encode({'status': 'WITHHELD_UNSEALED', 'reason': str(exc)[:1000],
                            'publication': 'NOT_ATTEMPTED'}), budget)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive-dir', 'anchor-dir', 'cache', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(encode(prepare(args.archive_dir, args.anchor_dir, args.cache, args.output)).decode())


if __name__ == '__main__':
    main()
