"""Activity report accounting must retain revocation and selected-edition boundaries."""
import gzip
import json
import sqlite3
from pathlib import Path

import pytest
from jsonschema import ValidationError

from cdr_report_terms import delivered, sha
from cdr_report_terms_contract import validate_rows
from cdr_report_terms_store import Snapshot
from tests.test_cdr_report_terms_routes import write

ROOT = Path(__file__).parent / 'fixtures' / 'activity-v4'
CAPABILITY = 'savings_activity_calculation'


def bridge_at(root):
    bridge = json.loads(gzip.decompress((ROOT / 'actual-bridge.json.gz').read_bytes()))
    for descriptor in bridge['assets']:
        (root / descriptor['name']).write_bytes((ROOT / 'blobs' / descriptor['sha256']).read_bytes())
    return bridge, bridge['context']['manifest']


@pytest.mark.parametrize('fault', ['unknown_capability', 'namespace_version', 'index_capability',
                                  'shard_version', 'details_identity', 'category'])
def test_activity_report_rejects_wrong_route_or_destination(tmp_path, fault):
    bridge, manifest = bridge_at(tmp_path)
    routes = manifest['executable_v4']['capabilities']
    route = routes[CAPABILITY]
    if fault == 'unknown_capability':
        routes['unknown'] = routes.pop(CAPABILITY)
    elif fault == 'namespace_version':
        manifest['executable_v4']['schema_version'] = 3
    elif fault == 'index_capability':
        index = json.loads(gzip.decompress((tmp_path / route['index']['name']).read_bytes()))
        index['capability'] = 'savings_calculation'
        route['index'] = write(tmp_path, route['index']['name'], index)
    elif fault == 'shard_version':
        name, descriptor = next(iter(route['shards'].items()))
        shard = json.loads(gzip.decompress((tmp_path / descriptor['name']).read_bytes()))
        shard['schema_version'] = 3
        route['shards'][name] = write(tmp_path, descriptor['name'], shard)
    elif fault == 'details_identity':
        manifest['files']['details']['sha256'] = '0' * 64
    else:
        key = bridge['selection']['subject']['scope']['productKey']
        bridge['context']['details']['products'][key]['displayIdentity']['productCategory'] = 'TERM_DEPOSITS'
    with pytest.raises((ValueError, ValidationError)):
        delivered(tmp_path, manifest, bridge['context'])


def test_activity_selected_edition_passes_closed_report_contract_without_approval(tmp_path):
    bridge, manifest = bridge_at(tmp_path)
    entries = delivered(tmp_path, manifest, bridge['context'])
    rows = {key: dict(status='unavailable', reason='selected observation unavailable',
                     evidence_class='technical_fixture', bank_approved=None, delivered=value)
            for key, value in entries.items()}
    validate_rows(rows)
    assert len(rows) == 1
    for row in rows.values():
        assert row['delivered'][0]['capability'] == CAPABILITY
        assert row['delivered'][0]['bank_acceptance'] == 'unclassified'


def test_activity_latest_revocation_and_all_publication_states_are_reported(tmp_path):
    raw = b'private technical review evidence'
    checksum = sha(raw)
    blob = tmp_path / 'blobs' / checksum[:2] / checksum
    blob.parent.mkdir(parents=True)
    blob.write_bytes(raw)
    with sqlite3.connect(tmp_path / 'evidence.sqlite3') as db:
        db.executescript('''
            CREATE TABLE executable_registry_subjects(subject_id,wire_version,capability,scope_id,product_key,observation_id);
            CREATE TABLE executable_reviews_v4(sequence,review_id,decision,reviewed_at,evidence_sha256,subject_id);
            CREATE TABLE executable_publications_v4(sequence,publication_id,observation_id,identity_sha256,published_at,capability,state,product_key);
        ''')
        db.execute('INSERT INTO executable_registry_subjects VALUES (?,?,?,?,?,?)', ('s', 4, CAPABILITY, 'scope', 'p', 'o'))
        for sequence, decision, state in [(1, 'approved', 'active'), (2, 'revoked', 'removed')]:
            db.execute('INSERT INTO executable_reviews_v4 VALUES (?,?,?,?,?,?)',
                       (sequence, str(sequence), decision, '2026-01-12T01:00:00Z', checksum, 's'))
            db.execute('INSERT INTO executable_publications_v4 VALUES (?,?,?,?,?,?,?,?)',
                       (sequence, str(sequence), 'o', checksum, '2026-01-12T01:00:00Z', CAPABILITY, state, 'p'))
    view = Snapshot(tmp_path)
    try:
        result = view.executables({'product_key': 'p', 'observation_id': 'o'})
        subject = result['subjects'][0]
        assert subject['recorded_review']['decision'] == 'revoked'
        assert subject['current_approval_revalidated'] is False
        assert 'unavailable_reason' not in subject
        assert [p['state'] for p in result['publications']] == ['active', 'removed']
        assert {p['capability'] for p in result['publications']} == {CAPABILITY}
        assert view.executables({'product_key': 'other', 'observation_id': 'o'})['publications'] == []
        blob.write_bytes(b'tampered review')
        with pytest.raises(ValueError, match='identity'):
            view.executables({'product_key': 'p', 'observation_id': 'o'})
    finally:
        view.close()
