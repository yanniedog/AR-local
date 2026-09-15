"""Append-only independent executable approval; hashes never substitute for tests."""
from __future__ import annotations

import json

from .executable_contract import REVIEW_CHECKS, validate_template
from .executable_benchmarks import verify_benchmark
from .executable_sources import validate_current_sources, source_checked
from .identity import canonical_json, digest, timestamp


def source_snapshot(store, template):
    validate_current_sources(store, template)
    reviews = []
    for identity in template['termRevisionIds']:
        row = store.db.execute('SELECT review_id FROM reviews WHERE term_revision_id=? ORDER BY sequence DESC LIMIT 1',
                               (identity,)).fetchone()
        reviews.append(row[0])
    return digest([template['id'], reviews])


@source_checked
def stage_template(store, template, *, interpreter, staged_at):
    validate_template(template)
    if template['evaluatorVersion'] != 'product-terms-engine-v8':
        raise ValueError('New executable staging requires evaluator v8 confirmed rate')
    if not interpreter or len(interpreter) > 256:
        raise ValueError('Executable interpreter identity required')
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        source_snapshot(store, template)
        previous = store.db.execute('SELECT template_json FROM executable_templates WHERE template_id=?', (template['id'],)).fetchone()
        if previous:
            if previous[0] != canonical_json(template):
                raise ValueError('Executable template identity collision')
            return template['id']
        fields = (template['id'], template['sourceObservationId'], template['productKey'], template['cohortKey'],
                  template['selectedRate']['rateIndex'], interpreter, timestamp(staged_at), canonical_json(template))
        store.db.execute('INSERT INTO executable_templates (template_id,observation_id,product_key,cohort_key,rate_index,interpreter,staged_at,template_json) VALUES (?,?,?,?,?,?,?,?)', fields)
        for identity in template['termRevisionIds']:
            store.db.execute('INSERT INTO executable_template_terms VALUES (?,?)', (template['id'], identity))
        for identity in template['documentVersionIds']:
            store.db.execute('INSERT INTO executable_template_documents VALUES (?,?)', (template['id'], identity))
    return template['id']


def _approval_evidence(store, template, evidence_sha, previous_review_id):
    evidence = json.loads(store.read_blob(evidence_sha))
    if (set(evidence) != {'schemaVersion', 'templateId', 'adapterVersion', 'evaluatorVersion',
                         'sourceSnapshotSha256', 'benchmarkResultSha256', 'checks', 'passed', 'previousReviewId'}
            or evidence['schemaVersion'] != 1 or evidence['passed'] is not True
            or not isinstance(evidence['checks'], list) or set(evidence['checks']) != REVIEW_CHECKS
            or len(evidence['checks']) != len(REVIEW_CHECKS)):
        raise ValueError('Independent executable review checks missing')
    if evidence['previousReviewId'] != previous_review_id:
        raise ValueError('Executable approval previous review changed')
    if any(evidence[k] != template[t] for k, t in (
            ('templateId', 'id'), ('adapterVersion', 'adapterVersion'), ('evaluatorVersion', 'evaluatorVersion'))):
        raise ValueError('Executable approval evidence identity mismatch')
    if evidence['sourceSnapshotSha256'] != source_snapshot(store, template):
        raise ValueError('Executable approval source review changed')
    verify_benchmark(store, evidence['benchmarkResultSha256'], template)
    return evidence


@source_checked
def review_template(store, template_id, *, decision, reviewer, reviewer_kind, reviewed_at, evidence_sha256, reason,
                    expected_previous_review_id):
    if decision not in {'approved', 'rejected', 'revoked'} or not reviewer or not reason or reviewer_kind not in {'human', 'deterministic'}:
        raise ValueError('Independent executable disposition required')
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        row = store.db.execute('SELECT * FROM executable_templates WHERE template_id=?', (template_id,)).fetchone()
        if row is None or reviewer == row['interpreter']:
            raise ValueError('Executable approval requires a separate reviewer')
        template = json.loads(row['template_json'])
        previous = store.db.execute('SELECT review_id FROM executable_reviews WHERE template_id=? ORDER BY sequence DESC LIMIT 1',
                                    (template_id,)).fetchone()
        if (previous[0] if previous else None) != expected_previous_review_id:
            raise ValueError('Executable review CAS changed')
        benchmark = None
        if decision == 'approved':
            if template['evaluatorVersion'] != 'product-terms-engine-v8':
                raise ValueError('New executable approval requires evaluator v8 confirmed rate')
            benchmark = _approval_evidence(store, template, evidence_sha256, expected_previous_review_id)['benchmarkResultSha256']
        else:
            evidence = json.loads(store.read_blob(evidence_sha256))
            if evidence.get('templateId') != template_id or evidence.get('decision') != decision:
                raise ValueError('Negative executable review binds another template/decision')
        reviewed = timestamp(reviewed_at)
        if reviewed < row['staged_at']:
            raise ValueError('Executable review predates staging')
        fields = (template_id, decision, reviewer, reviewer_kind, reviewed, evidence_sha256, benchmark, reason)
        identity = digest(fields)
        store.db.execute('INSERT OR IGNORE INTO executable_reviews (review_id,template_id,decision,reviewer,reviewer_kind,reviewed_at,evidence_sha256,benchmark_sha256,reason) VALUES (?,?,?,?,?,?,?,?,?)', (identity, *fields))
    return identity


def current_approval(store, template):
    row = store.db.execute('SELECT * FROM executable_reviews WHERE template_id=? ORDER BY sequence DESC LIMIT 1',
                           (template['id'],)).fetchone()
    if row is None or row['decision'] != 'approved':
        return None
    previous = store.db.execute('SELECT review_id FROM executable_reviews WHERE template_id=? AND sequence<? ORDER BY sequence DESC LIMIT 1',
                                (template['id'], row['sequence'])).fetchone()
    _approval_evidence(store, template, row['evidence_sha256'], previous[0] if previous else None)
    return {'templateId': template['id'], 'reviewId': row['review_id'], 'reviewEvidenceSha256': row['evidence_sha256'],
            'benchmarkResultSha256': row['benchmark_sha256'], 'reviewedAt': row['reviewed_at'],
            'review': {key: 'verified' for key in ('applicability', 'materialTerms', 'feeCoverage', 'rateSchedule')}}
