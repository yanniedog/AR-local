"""Independent monetary reviews with exact source/material/benchmark association."""
import json
from .identity import canonical_json,digest,timestamp
from .executable_v2_contract import validate_review_time
from .executable_v3_contract import CAPABILITY,ADAPTER,EVALUATOR
from .executable_v3_sources import source_snapshot
from .executable_v3_evidence import evidence_checked,evidence_operation

CHECKS=('source_alignment','historical_coverage','scope_coverage','input_bindings','rule_semantics','rate_schedule','material_terms','fee_coverage','posting_and_residue','benchmark')
POSITIVE={'schemaVersion','subjectId','capability','adapterVersion','evaluatorVersion','previousReviewId','sourceSnapshotSha256','authorityGraphSha256','benchmarkResultSha256','materialProjection','checks','passed'}


def material_projection(subject):
    authorities={x['id']:x for x in subject['authorityGraph']['authorities']}
    if subject['capability']=='mortgage_calculation':
        return {'scope':subject['scope'],'routing':subject['routing'],'target':subject['target'],
                'completedPeriod':subject['authorityGraph']['completedPeriod'],'policy':subject['policy'],
                'authorities':[authorities[k] for k in subject['policy']['authorityIds']]}
    return {'scope':subject['scope'],'routing':subject['routing'],'completedPeriod':subject['authorityGraph']['completedPeriod'],
        'inputDefinitions':subject['policy']['inputDefinitions'],'eligibility':subject['policy']['eligibility'],
        'fees':subject['policy']['fees'],'postingInventory':subject['policy']['postingInventory'],
        'intervals':[{'interval':interval,'authority':authorities[interval['authorityId']]} for interval in subject['policy']['intervals']]}


def validate_completion_proof(store,subject):
    graph=subject['authorityGraph'];bound=graph['completedPeriod']
    with evidence_operation(store) as operation:
        proof=json.loads(operation.read_blob(bound['sourceSnapshotSha256']))
    expected={'schemaVersion':1,'kind':'monetary_completed_period_v1','productKey':subject['scope']['productKey'],
        'asOf':bound['asOf'],'timezone':bound['timezone'],'completedThroughExclusive':bound['completedThroughExclusive'],
        'authorityIds':sorted(x['id'] for x in graph['authorities']),'evidenceIds':sorted(bound['evidenceIds'])}
    if proof!=expected:raise ValueError('Monetary completed-period proof content differs')


def _positive(store,subject,evidence_sha,previous):
    with evidence_operation(store) as operation:evidence=json.loads(operation.read_blob(evidence_sha))
    if (not isinstance(evidence,dict) or set(evidence)!=POSITIVE or evidence['schemaVersion']!=3 or evidence['passed'] is not True
        or evidence['checks']!=sorted(CHECKS) or evidence['subjectId']!=subject['id'] or evidence['previousReviewId']!=previous
        or any(evidence[k]!=subject[k] for k in ('capability','adapterVersion','evaluatorVersion'))
        or evidence['authorityGraphSha256']!=subject['authorityGraph']['identitySha256']
        or evidence['materialProjection']!=material_projection(subject)):
        raise ValueError('Monetary independent review projection/identity differs')
    latest=store.db.execute('SELECT subject_id FROM executable_subjects_v3 WHERE scope_id=? ORDER BY sequence DESC LIMIT 1',(subject['scopeId'],)).fetchone()
    if latest is None or latest[0]!=subject['id']:raise ValueError('Monetary reviewed subject superseded')
    if evidence['sourceSnapshotSha256']!=source_snapshot(store,subject):raise ValueError('Monetary reviewed source snapshot changed')
    validate_completion_proof(store,subject)
    from .executable_v3_benchmarks import verify_benchmark
    verify_benchmark(store,evidence['benchmarkResultSha256'],subject)
    return evidence


@evidence_checked
def review_subject(store,subject_id,*,decision,reviewer,reviewer_kind,reviewed_at,evidence_sha256,reason,expected_previous_review_id):
    if (decision not in ('approved','rejected','revoked') or reviewer_kind not in ('human','deterministic')
        or not isinstance(reviewer,str) or not reviewer.strip() or len(reviewer)>256
        or not isinstance(reason,str) or not reason.strip() or len(reason)>4000):raise ValueError('Independent monetary disposition required')
    validate_review_time(reviewed_at);reviewed=timestamp(reviewed_at)
    if store.db.in_transaction:raise ValueError('Monetary review requires own transaction')
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        row=store.db.execute('SELECT * FROM executable_subjects_v3 WHERE subject_id=?',(subject_id,)).fetchone()
        if row is None or reviewer.strip()==row['interpreter'].strip():raise ValueError('Monetary review requires separate reviewer')
        subject=json.loads(row['subject_json'])
        previous=store.db.execute('SELECT * FROM executable_reviews_v3 WHERE subject_id=? ORDER BY sequence DESC LIMIT 1',(subject_id,)).fetchone()
        if (previous['review_id'] if previous else None)!=expected_previous_review_id:raise ValueError('Monetary review CAS changed')
        if reviewed<row['staged_at'] or previous and reviewed<previous['reviewed_at']:raise ValueError('Monetary review predates predecessor')
        snapshot,graph,benchmark=None,None,None
        if decision=='approved':
            proof=_positive(store,subject,evidence_sha256,expected_previous_review_id)
            snapshot,graph,benchmark=(proof[k] for k in ('sourceSnapshotSha256','authorityGraphSha256','benchmarkResultSha256'))
        else:
            with evidence_operation(store) as operation:proof=json.loads(operation.read_blob(evidence_sha256))
            if proof!={'schemaVersion':3,'subjectId':subject_id,'decision':decision,'previousReviewId':expected_previous_review_id,'reason':reason}:
                raise ValueError('Monetary negative review identity differs')
        fields=(subject_id,expected_previous_review_id,decision,reviewer,reviewer_kind,reviewed,evidence_sha256,snapshot,graph,benchmark,reason)
        identity=digest(fields)
        store.db.execute('INSERT INTO executable_reviews_v3(review_id,subject_id,previous_review_id,decision,reviewer,reviewer_kind,reviewed_at,evidence_sha256,source_snapshot_sha256,authority_graph_sha256,benchmark_sha256,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(identity,*fields))
    return identity


@evidence_checked
def current_approval(store,subject):
    row=store.db.execute('SELECT * FROM executable_reviews_v3 WHERE subject_id=? ORDER BY sequence DESC LIMIT 1',(subject['id'],)).fetchone()
    if row is None:raise ValueError('Monetary current subject has no independent disposition')
    if row['decision']!='approved':return None
    proof=_positive(store,subject,row['evidence_sha256'],row['previous_review_id'])
    if any(proof[k]!=row[v] for k,v in (('sourceSnapshotSha256','source_snapshot_sha256'),('authorityGraphSha256','authority_graph_sha256'),('benchmarkResultSha256','benchmark_sha256'))):
        raise ValueError('Monetary immutable approval evidence differs')
    return dict(subjectId=subject['id'],capability=subject['capability'],reviewId=row['review_id'],reviewEvidenceSha256=row['evidence_sha256'],
        benchmarkResultSha256=row['benchmark_sha256'],authorityGraphSha256=row['authority_graph_sha256'],reviewedAt=row['reviewed_at'],checks={k:'verified' for k in CHECKS})
