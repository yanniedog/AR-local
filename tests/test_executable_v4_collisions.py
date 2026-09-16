"""Shared registry IDs cannot collide across v3/v4, in either insertion order."""
import importlib
import sqlite3

import pytest

from cdr_terms.executable_registry import migrate_executable_registry, stage_subject, review_subject
from cdr_terms.identity import canonical_json
from cdr_terms.observation_checks import current_observation
from tests.executable_v3_fixture import monetary_protocol
from tests.test_executable_v4_sources import activity_protocol


@pytest.mark.parametrize('source_version', [3, 4])
@pytest.mark.parametrize('kind', ['reviews', 'publications'])
def test_cross_version_identity_collision_is_refused(request, source_version, kind):
    store, subject, _ = request.getfixturevalue('monetary_protocol' if source_version == 3 else 'activity_protocol')
    now = '2026-01-12T01:00:00Z'
    for version in (3, 4):
        migrate_executable_registry(store, wire_version=version, applied_at=now)
    stage_subject(store, subject, interpreter='technical-writer', staged_at=now)
    reason = 'Technical namespace isolation control'
    evidence = store.put_blob(canonical_json(dict(schemaVersion=source_version, subjectId=subject['id'],
        decision='rejected', previousReviewId=None, reason=reason)).encode())
    review_subject(store, subject['id'], decision='rejected', reviewer='independent-technical',
        reviewer_kind='deterministic', reviewed_at=now, evidence_sha256=evidence,
        reason=reason, expected_previous_review_id=None)
    if kind == 'publications':
        module = importlib.import_module(f'cdr_terms.executable_v{source_version}_publication')
        key = subject['scope']['productKey']
        module.publish_asset(store, key, routing=subject['routing'], expected_previous_publication_id=None,
            expected_observation_id=current_observation(store, key)['observation_id'], published_at=now)
    source, target = f'executable_{kind}_v{source_version}', f'executable_{kind}_v{7-source_version}'
    row = dict(store.db.execute(f'SELECT * FROM {source}').fetchone())
    row.pop('sequence')
    if kind == 'publications':
        row['capability'] = 'savings_activity_calculation' if source_version == 3 else 'savings_calculation'
    fields = ','.join(row)
    with pytest.raises(sqlite3.IntegrityError, match='cross-version executable'):
        store.db.execute(f'INSERT INTO {target} ({fields}) VALUES ({",".join("?" for _ in row)})', tuple(row.values()))
