import pytest
import json
from tests.executable_v3_fixture import monetary_protocol,reidentify
from cdr_terms.executable_v3_sources import source_snapshot
from cdr_terms.identity import canonical_json
from cdr_terms.revisions import review_term


def _successor(store,subject,lower,kind='changed'):
    """Append independent technical rows; never mutate the retained prior policy."""
    def clone(table,updates):
        row=dict(store.db.execute('SELECT * FROM '+table+' LIMIT 1').fetchone());row.update(updates)
        store.db.execute('INSERT INTO '+table+' ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
    original=subject['termRevisionIds'][0];successor='e'*64
    raw=b'Separately retained later technical policy';sha=store.put_blob(raw)
    with store.db:
        clone('document_versions',dict(document_version_id='d'*64,content_sha256=sha,byte_size=len(raw)))
        clone('extractions',dict(extraction_id='c'*64,document_version_id='d'*64,text_sha256=sha))
        clone('clauses',dict(clause_id='b'*64,extraction_id='c'*64,text=raw.decode()))
        applicability=json.loads(store.db.execute('SELECT applicability_json FROM term_revisions WHERE term_revision_id=?',(original,)).fetchone()[0])
        applicability.update(effective_from=lower,effective_to='2026-03-01')
        clone('term_revisions',dict(term_revision_id=successor,applicability_json=canonical_json(applicability)))
        store.db.execute('INSERT INTO term_sources VALUES (?,?)',(successor,'b'*64))
    from cdr_terms.revisions import REVIEW_CHECKS,record_change
    proof=store.put_blob(canonical_json(dict(term_revision_id=successor,passed=True,checks=sorted(REVIEW_CHECKS))).encode())
    review_term(store,successor,status='validated',reviewer='later-independent',reviewer_kind='human',reviewed_at='2026-02-01T00:00:00Z',evidence_sha256=proof,reason='Separate later technical source')
    proof=store.put_blob(canonical_json(dict(passed=True,kind=kind,before_revision_id=original,after_revision_id=successor)).encode())
    record_change(store,product_key=subject['scope']['productKey'],before_revision_id=original,after_revision_id=successor,kind=kind,observed_at='2026-02-01T00:00:00Z',evidence_sha256=proof)


def test_source_backed_later_successor_preserves_historical_snapshot(monetary_protocol):
    store,subject,_=monetary_protocol
    before=source_snapshot(store,subject)
    _successor(store,subject,subject['scope']['toExclusive'])
    assert source_snapshot(store,subject)==before


@pytest.mark.parametrize('kind,lower',[('changed','2026-01-05'),('extraction_corrected','2026-02-01')])
def test_overlapping_change_or_correction_refuses(monetary_protocol,kind,lower):
    store,subject,_=monetary_protocol;_successor(store,subject,lower,kind)
    with pytest.raises(ValueError,match='no longer validated'):source_snapshot(store,subject)


def test_within_horizon_successor_checks_only_prior_used_field_interval(monetary_protocol):
    import copy
    from cdr_terms.executable_v3_sources import _revisions
    from cdr_terms.executable_v3_evidence import EvidenceOperation
    store,subject,_=monetary_protocol;_successor(store,subject,'2026-01-05')
    # Focus the revision selector on two separately approved rate authority spans.
    old=subject['authorityGraph']['authorities'][0]
    old['fieldCoverage']=[dict(next(x for x in old['fieldCoverage'] if x['field']=='rates'),toExclusive='2026-01-05')]
    later=copy.deepcopy(old);later['id']='a'*64
    later['fieldCoverage'][0].update(evidenceIds=['b'*64],**{'from':'2026-01-05','toExclusive':subject['scope']['toExclusive']})
    subject['authorityGraph']['authorities'].append(later)
    first=subject['policy']['intervals'][0];second=copy.deepcopy(first)
    first['toExclusive']='2026-01-05';second.update(authorityId=later['id'],**{'from':'2026-01-05'})
    subject['policy']['intervals'].append(second);subject['termRevisionIds'].append('e'*64)
    assert len(_revisions(store,subject,EvidenceOperation(store)))==2
    old['fieldCoverage'][0]['toExclusive']='2026-01-06';first['toExclusive']='2026-01-06'
    with pytest.raises(ValueError,match='no longer validated'):_revisions(store,subject,EvidenceOperation(store))


def test_private_originals_and_current_routing(monetary_protocol):
    store,subject,_=monetary_protocol
    assert len(source_snapshot(store,subject))==64


def test_original_metadata_without_raw_bytes_refuses(monetary_protocol):
    store,subject,_=monetary_protocol
    sha=subject['evidence'][0]['documentSha256']
    (store.blobs/sha[:2]/sha).unlink()
    with pytest.raises(ValueError,match='Unsafe monetary source'):source_snapshot(store,subject)


def test_negative_source_review_invalidates_historical_reuse(monetary_protocol):
    store,subject,_=monetary_protocol
    revision=subject['termRevisionIds'][0]
    proof=store.put_blob(canonical_json({'term_revision_id':revision}).encode())
    review_term(store,revision,status='rejected',reviewer='correction-reviewer',reviewer_kind='human',reviewed_at='2026-01-13T00:00:00Z',evidence_sha256=proof,reason='Technical correction')
    with pytest.raises(ValueError,match='no longer validated'):source_snapshot(store,subject)
