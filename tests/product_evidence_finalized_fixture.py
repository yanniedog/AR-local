"""Captured financial bodies; selection/ledger/base gzip are technical controls.

These local fixtures are not evidence of a selected production observation.
"""
import json
from pathlib import Path
import shutil

from app_payload_product_evidence_contract import canonical, digest
from app_payload_product_evidence_transport import compressed
from cdr_ledger_v2 import append_contract_event
from cdr_export_contract import build_contract
from cdr_product_evidence_source import FinalizedSource
from tests.test_app_payload_product_response_sources import real_source, DAY

WRITER = 'a' * 40  # Exact code-pin control, never production trust.
FACTS = 'product_evidence_v1'
RESPONSES = 'product_response_evidence_v1'
ENABLED = (FACTS, RESPONSES)


def finalized(tmp_path, *, observation_state='partial', dated_contract=False):
    captured = tmp_path / 'captured'; captured.mkdir()
    _, old_exports, old_contract, _, original = real_source(captured)
    exports = tmp_path / 'data/runs' / DAY / '_exports'
    exports.parent.mkdir(parents=True); shutil.copytree(old_exports, exports)
    state = tmp_path / 'data/state'; state.mkdir()
    contract_path = state / (f'export-contracts-v2/{DAY}/contract.json' if dated_contract else 'contract.json')
    contract_path.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(old_contract, contract_path)
    contract = json.loads(contract_path.read_bytes())
    if observation_state != 'partial':
        # Complete-schema control uses the retained completed-provider subset;
        # this is deliberately NOT a whole-population coverage assertion.
        contract['provider_states'] = [p for p in contract['provider_states'] if p['state'] not in ('partial', 'failed')]
        contract['coverage']['providers_attempted'] = sum(p['state'] != 'not_attempted' for p in contract['provider_states'])
        contract = build_contract(exports, observation_state=observation_state, **{k: contract[k] for k in (
            'observation_date', 'observed_at', 'source_path', 'completion_marker_path', 'coverage',
            'provider_states', 'register_hashes', 'normalization_version', 'artifacts')})
        contract_path.write_bytes(canonical(contract))
    event = append_contract_event(state, contract_path)
    captured_rows = json.loads((Path(__file__).parent / 'fixtures/product_facts_real_2026-05-19.json').read_bytes())['products']
    rates = sum(len(p['record'].get('depositRates', [])) + len(p['record'].get('lendingRates', [])) for p in captured_rows)
    assert rates > 0
    marker = dict(finalization_schema_version=2, ledger_state='finalized', run_date=DAY,
                  generation_id=contract['generation_id'], observation_state=contract['observation_state'],
                  export_contract_path=contract_path.relative_to(state).as_posix(), export_contract_digest=contract['contract_digest'],
                  ledger_event_digest=event['event_digest'], banks_counts={'rates': rates})
    (state / contract['completion_marker_path']).write_bytes(canonical(marker))
    pointer = dict(schema_version=2, observation_date=DAY, generation_id=contract['generation_id'],
                   observation_state=contract['observation_state'], ledger_event_digest=event['event_digest'],
                   marker_path=contract['completion_marker_path'], export_path=contract['source_path'])
    pointers = state / 'observation-pointers-v2'; pointers.mkdir()
    pointer_path = pointers / 'latest-observation.json'; pointer_path.write_bytes(canonical(pointer))
    if observation_state == 'complete': (pointers / 'latest-complete.json').write_bytes(canonical(pointer))
    root = tmp_path / 'base'; root.mkdir(); files = {}
    for key in ('core', 'details'):
        blob = compressed(canonical({'technical_control': key})); sha = digest(blob)
        name = f'{key}-{DAY}-{sha[:12]}.json.gz'; (root / name).write_bytes(blob)
        files[key] = dict(name=name, sha256=sha, bytes=len(blob), url='https://example.invalid/' + name)
    base = dict(schema_version=1, run_date=DAY, files=files,
                source_observation={k: contract[k] for k in ('generation_id', 'observation_date', 'observation_state', 'contract_digest')})
    (root / 'manifest.json').write_bytes(canonical(base))
    return dict(state=state, exports=exports, root=root, base=base, pointer=pointer_path,
                contract=contract_path, original=original)


def open_source(fixture, **pins):
    return FinalizedSource(fixture['state'], fixture['root'],
        expected_pointer_sha256=pins['pointer'] if 'pointer' in pins else digest(fixture['pointer'].read_bytes()),
        expected_manifest_sha256=pins['manifest'] if 'manifest' in pins else digest((fixture['root'] / 'manifest.json').read_bytes()))
