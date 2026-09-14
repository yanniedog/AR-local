"""One sequential resource-supervised acquisition batch; no model or authentication."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from cdr_terms.acquisition_batch import ADMISSION_SECONDS, has_work, run_batch, validate_batch_receipt
from cdr_terms.identity import byte_digest, canonical_json
from cdr_terms.store import EvidenceStore
from pi_terms_codex import MAX_INPUT_BYTES, private_directory, read_bounded, write_receipt


def runtime_guard(repo: Path, root: Path):
    """Same host/RSS/priority limits, also checked before each item/redirect."""
    from pi_cdr_quality_resources import Limits, aggregate, host_sample, host_violation, own_cgroup
    from pi_terms_worker import operating_window, priority_guard, utc_now
    baseline = previous = None
    limits = Limits(runtime_seconds=120)
    def check():
        nonlocal baseline, previous
        if not operating_window(utc_now()):
            return 'outside_analysis_window'
        reason = priority_guard(repo, root)
        if reason:
            return reason
        host = host_sample()
        if baseline is None:
            baseline = host
        reason = host_violation(host, baseline, limits, previous=previous)
        previous = host
        sample = aggregate(own_cgroup())
        if sample['rss_bytes'] >= limits.workload_bytes - limits.margin_bytes:
            return 'aggregate_rss_early_stop'
        if sample['swap_bytes']:
            return 'workload_swapped'
        return reason
    return check


def run(root: Path) -> dict:
    private_directory(root)
    body = read_bounded(root / 'input.json', MAX_INPUT_BYTES)
    input_sha = byte_digest(body)
    value = json.loads(body)
    evidence = Path(value['evidence_root'])
    private_directory(evidence)
    # This process gets no subscription auth arguments, environment or client.
    with EvidenceStore(evidence) as store:
        deadline = value.get('admission_deadline')
        if deadline is None and not has_work(store):
            deadline = time.monotonic() + ADMISSION_SECONDS
        if type(deadline) not in (int, float):
            raise ValueError('Parent-bound acquisition admission deadline required')
        result = run_batch(store, registry_context=value['registry_context'], deadline=deadline,
                           guard=runtime_guard(Path(__file__).resolve().parent, evidence))
    receipt = {'schema_version': 2, 'input_sha256': input_sha, **result}
    validate_batch_receipt(receipt)
    body = canonical_json(receipt).encode('utf-8')
    write_receipt(root / 'batch.json', receipt)
    write_receipt(root / 'acquisition.json', {
        'schema_version': 2, 'input_sha256': input_sha,
        'result': result['result'], 'network_called': result['network_called'], 'codex_called': False,
        'batch_file_sha256': byte_digest(body), 'batch_file_bytes': len(body)})
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-root', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run(args.job_root)
    except (OSError, ValueError, RuntimeError, KeyError):
        print(json.dumps({'result': 'DEFERRED', 'reason': 'acquisition_receipt_unavailable', 'codex_called': False}))
        return 2
    print(json.dumps({key: result[key] for key in ('result', 'network_called', 'codex_called')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
