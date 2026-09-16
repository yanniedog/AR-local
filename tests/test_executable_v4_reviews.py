"""Technical disposition, CAS and publication isolation; no bank acceptance."""
import copy
import pytest
from cdr_terms.identity import canonical_json, digest
from cdr_terms.executable_registry import migrate_executable_registry, stage_subject, review_subject
from cdr_terms.executable_v4_reviews import current_approval, material_projection
from cdr_terms.executable_v4_publication import build_asset, publish_asset
from tests.test_executable_v4_sources import activity_protocol


def staged(store, subject):
    now = '2026-01-12T01:00:00Z'
    for version in (3, 4):
        migrate_executable_registry(store, wire_version=version, applied_at=now)
    stage_subject(store, subject, interpreter='technical-writer', staged_at=now)
    return now


def disposition(store, subject, now, *, reviewer='independent-technical', previous=None):
    reason = 'Technical refusal pending independent activity benchmark'
    evidence = store.put_blob(canonical_json(dict(schemaVersion=4, subjectId=subject['id'],
        decision='rejected', previousReviewId=previous, reason=reason)).encode())
    return review_subject(store, subject['id'], decision='rejected', reviewer=reviewer,
        reviewer_kind='deterministic', reviewed_at=now, evidence_sha256=evidence, reason=reason,
        expected_previous_review_id=previous)


def test_shared_controller_rejects_same_author_and_preserves_review_cas(activity_protocol):
    store, subject, _ = activity_protocol
    now = staged(store, subject)
    with pytest.raises(ValueError, match='separate reviewer'):
        disposition(store, subject, now, reviewer='technical-writer')
    assert not store.db.in_transaction
    review = disposition(store, subject, now)
    with pytest.raises(ValueError, match='CAS changed'):
        disposition(store, subject, now)
    assert current_approval(store, subject) is None
    assert store.db.execute('SELECT review_id FROM executable_reviews_v4').fetchone()[0] == review
    assert store.db.execute('SELECT count(*) FROM executable_reviews_v3').fetchone()[0] == 0


def test_unreviewed_activity_cannot_publish_and_rejection_is_tombstone(activity_protocol):
    from cdr_terms.observation_checks import current_observation
    store, subject, _ = activity_protocol
    now = staged(store, subject); key = subject['scope']['productKey']
    with pytest.raises(ValueError, match='no independent disposition'):
        build_asset(store, key, routing=subject['routing'])
    disposition(store, subject, now)
    assert build_asset(store, key, routing=subject['routing']) is None
    arguments = dict(routing=subject['routing'], expected_previous_publication_id=None,
        expected_observation_id=current_observation(store, key)['observation_id'], published_at=now)
    publication = publish_asset(store, key, **arguments)
    row = store.db.execute('SELECT * FROM executable_publications_v4').fetchone()
    assert row['publication_id'] == publication and row['state'] == 'removed' and row['payload_json'] is None
    with pytest.raises(ValueError, match='predecessor CAS changed'):
        publish_asset(store, key, **arguments)


def test_material_projection_includes_activity_policy_and_assessment_authorities(activity_protocol):
    _, subject, _ = activity_protocol
    original = digest(material_projection(subject))
    changed = copy.deepcopy(subject)
    changed['policy']['bonus']['tiers'][0]['annualRate'] = '0.25'
    assert digest(material_projection(changed)) != original
    changed = copy.deepcopy(subject)
    changed['authorityGraph']['authorities'].pop()
    assert digest(material_projection(changed)) != original
