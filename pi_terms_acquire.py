"""One resource-supervised document acquisition; no model or authentication."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cdr_terms.acquisition import FetchPolicy
from cdr_terms.acquisitions_queue import process_next_acquisition
from cdr_terms.identity import byte_digest
from cdr_terms.store import EvidenceStore
from pi_terms_codex import MAX_INPUT_BYTES, private_directory, read_bounded, write_receipt


def run(root: Path) -> dict:
    private_directory(root)
    body = read_bounded(root / 'input.json', MAX_INPUT_BYTES)
    input_sha = byte_digest(body)
    value = json.loads(body)
    evidence = Path(value['evidence_root'])
    private_directory(evidence)
    # This process gets no subscription auth arguments, environment or client.
    with EvidenceStore(evidence) as store:
        result = process_next_acquisition(store, registry_context=value['registry_context'], policy=FetchPolicy())
    receipt = {'schema_version': 1, 'input_sha256': input_sha, **result}
    write_receipt(root / 'acquisition.json', receipt)
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
