"""Capability adapter for the shared append-only executable approval controller."""
import json

from .executable_sources import source_checked
from .executable_v2_contract import CHECKS, schema_validate, validate_review_time
from .executable_v2_sources import source_snapshot
from .executable_v2_benchmarks import verify_benchmark
from .identity import canonical_json, digest, timestamp


def _positive(store, subject, evidence_sha, previous):
    evidence = json.loads(store.read_blob(evidence_sha))
    schema_validate(evidence,'executable-positive-review-v2.schema.json')
    if evidence['subjectId'] != subject['id'] or evidence['previousReviewId'] != previous or any(evidence[k] != subject[k] for k in ('capability','adapterVersion','evaluatorVersion')):
        raise ValueError('Eligibility approval exact subject/predecessor differs')
    latest = store.db.execute('SELECT subject_id FROM executable_subjects_v2 WHERE scope_id=? ORDER BY sequence DESC LIMIT 1',(subject['scopeId'],)).fetchone()
    if latest is None or latest[0] != subject['id']:
        raise ValueError('Eligibility subject was superseded')
    if evidence['sourceSnapshotSha256'] != source_snapshot(store,subject):
        raise ValueError('Eligibility approval source snapshot changed')
    verify_benchmark(store,evidence['benchmarkResultSha256'],subject)
    return evidence


@source_checked
def review_subject(store, subject_id, *, decision, reviewer, reviewer_kind, reviewed_at, evidence_sha256, reason, expected_previous_review_id):
    if (decision not in ('approved','rejected','revoked') or reviewer_kind not in ('human','deterministic')
            or not isinstance(reviewer,str) or not reviewer.strip() or len(reviewer)>256
            or not isinstance(reason,str) or not reason.strip() or len(reason)>4000):
        raise ValueError('Independent executable disposition required')
    validate_review_time(reviewed_at)
    reviewed = timestamp(reviewed_at)
    if store.db.in_transaction:
        raise ValueError('Eligibility review needs its own transaction')
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        row = store.db.execute('SELECT * FROM executable_subjects_v2 WHERE subject_id=?',(subject_id,)).fetchone()
        if row is None or row['interpreter'] == reviewer:
            raise ValueError('Eligibility review requires separate reviewer')
        subject = json.loads(row['subject_json'])
        previous = store.db.execute('SELECT * FROM executable_reviews_v2 WHERE subject_id=? ORDER BY sequence DESC LIMIT 1',(subject_id,)).fetchone()
        if (previous['review_id'] if previous else None) != expected_previous_review_id:
            raise ValueError('Eligibility review CAS changed')
        if reviewed < row['staged_at'] or previous and reviewed < previous['reviewed_at']:
            raise ValueError('Eligibility review predates its predecessor')
        snapshot, benchmark = None, None
        if decision == 'approved':
            evidence = _positive(store,subject,evidence_sha256,expected_previous_review_id)
            snapshot, benchmark = evidence['sourceSnapshotSha256'], evidence['benchmarkResultSha256']
        else:
            evidence = json.loads(store.read_blob(evidence_sha256))
            schema_validate(evidence,'executable-negative-review-v2.schema.json')
            if any(evidence[k] != v for k,v in (('subjectId',subject_id),('decision',decision),('previousReviewId',expected_previous_review_id),('reason',reason))):
                raise ValueError('Eligibility negative review identity differs')
        fields = (subject_id,expected_previous_review_id,decision,reviewer,reviewer_kind,reviewed,evidence_sha256,snapshot,benchmark,reason)
        identity = digest(fields)
        store.db.execute('INSERT INTO executable_reviews_v2(review_id,subject_id,previous_review_id,decision,reviewer,reviewer_kind,reviewed_at,evidence_sha256,source_snapshot_sha256,benchmark_sha256,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(identity,*fields))
    return identity


@source_checked
def current_approval(store, subject):
    review = store.db.execute('SELECT * FROM executable_reviews_v2 WHERE subject_id=? ORDER BY sequence DESC LIMIT 1',(subject['id'],)).fetchone()
    if review is None:
        raise ValueError('Eligibility current subject has no independent disposition')
    if review['decision'] != 'approved':
        return None
    evidence = _positive(store,subject,review['evidence_sha256'],review['previous_review_id'])
    if evidence['sourceSnapshotSha256'] != review['source_snapshot_sha256'] or evidence['benchmarkResultSha256'] != review['benchmark_sha256']:
        raise ValueError('Eligibility immutable review evidence differs')
    return dict(subjectId=subject['id'],capability=subject['capability'],reviewId=review['review_id'],
        reviewEvidenceSha256=review['evidence_sha256'],benchmarkResultSha256=review['benchmark_sha256'],
        sourceSnapshotSha256=review['source_snapshot_sha256'],reviewedAt=review['reviewed_at'],
        checks={key:'verified' for key in CHECKS})
