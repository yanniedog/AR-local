"""Technical structured contract only, never source-admissible authority."""
import json
from cdr_terms.executable_v3_migration import ROOT
from cdr_terms.executable_v3_contract import identity
from cdr_terms.executable_v3_graph import POSTING_FIELDS
from cdr_terms.identity import digest


def reidentify(subject):
    mapping={}
    for authority in subject['authorityGraph']['authorities']:
        old=authority['id'];authority['id']=identity(authority);mapping[old]=authority['id']
    for interval in subject['policy']['intervals']:
        interval['authorityId']=mapping.get(interval['authorityId'],interval['authorityId'])
    subject['authorityGraph']['identitySha256']=identity(subject['authorityGraph'],'identitySha256')
    subject['scopeId']=digest(['monetary-scope-v3',subject['capability'],subject['scope']])
    subject['id']=identity(subject)
    return subject


def subject():
    value=json.loads((ROOT/'controls/positive-technical-example.json').read_bytes())['subject']
    for authority in value['authorityGraph']['authorities']:
        for coverage in authority['fieldCoverage']:
            if coverage['field'] in POSTING_FIELDS:
                coverage['postingEventDates']=value['policy']['postingInventory']['dueDates'][:]
    return reidentify(value)


import pytest
from cdr_terms.store import EvidenceStore
from cdr_terms.identity import canonical_json,byte_digest
from cdr_terms.revisions import stage_term,review_term,REVIEW_CHECKS
from tests.test_cdr_terms_evidence import _staged_term
from tests.cdr_terms_source_fixture import source_generation
from app_payload_build import _gzip_bytes


@pytest.fixture
def monetary_protocol(tmp_path):
    yield from technical_protocol(tmp_path)


def technical_protocol(tmp_path,source_description=None,adopted_assets=None):
    value=subject();scope=value['scope'];now='2026-01-12T01:00:00Z';run_date='2026-01-12'
    data={'name':'Technical savings only','brand':'Protocol only','productId':'protocol','productCategory':'TRANS_AND_SAVINGS_ACCOUNTS'}
    if source_description:data['description']=source_description
    raw=canonical_json({'data':data,'links':{'self':'https://example.invalid/protocol'}}).encode()
    _,state,finalized=source_generation(tmp_path,run_date,now,raw)
    with EvidenceStore(tmp_path/'monetary-technical-store') as store:
        observation=store.observe(provider='Protocol only',product_key=scope['productKey'],record=json.loads(raw),source_bytes=raw,observed_at=now,ingest_id=finalized['generation_id'])
        version=store.db.execute('SELECT document_version_id FROM document_versions').fetchone()[0]
        doc=store.db.execute('SELECT document_id FROM document_versions').fetchone()[0]
        fixture=(store,observation,scope['productKey'],doc,version,raw,json.loads(raw)['data'])
        description_clause=[]
        def scoped(output):
            output['terms'][0].update(cohort=scope['cohortKey'],tier=scope['tierKey'],package=scope['packageKey'],effective_from=scope['from'],effective_to=scope['toExclusive'])
            if source_description:
                extraction=output['extraction_id'];text_sha=store.db.execute('SELECT text_sha256 FROM extractions WHERE extraction_id=?',(extraction,)).fetchone()[0]
                text=store.read_blob(text_sha).decode('utf8');start=text.index(source_description)
                clause=store.add_clause(extraction,start=start,end=start+len(source_description),section='description');description_clause.append(clause)
                locator=json.loads(store.db.execute('SELECT locator_json FROM clauses WHERE clause_id=?',(clause,)).fetchone()[0])
                output['clauses']=[dict(page=None,**locator,disposition='parameter',reason='Engineering source declaration')]
                output['terms'][0].update(parameter_key='product.description',value=source_description)
                output['unresolved']=['Engineering-only source specification; not bank interpretation']
        _,_,_,args=_staged_term(fixture,output_change=scoped)
        args['applicability'].update(cohort=scope['cohortKey'],tier=scope['tierKey'],package=scope['packageKey'],effective_from=scope['from'],effective_to=scope['toExclusive'])
        if source_description:args.update(parameter_key='product.description',value=source_description,clause_ids=description_clause)
        revision=stage_term(store,**args)
        proof=store.put_blob(canonical_json({'term_revision_id':revision,'passed':True,'checks':sorted(REVIEW_CHECKS)}).encode())
        review_term(store,revision,status='validated',reviewer='independent-technical',reviewer_kind='human',reviewed_at=now,evidence_sha256=proof,reason='Isolated technical fixture only')
        clause=store.db.execute('SELECT * FROM clauses WHERE clause_id=?',(args['clause_ids'][0],)).fetchone();ref=clause['clause_id']
        old=value['evidence'][0]['id']
        def replace(node):
            if isinstance(node,dict):return {k:replace(v) for k,v in node.items()}
            if isinstance(node,list):return [replace(x) for x in node]
            return ref if node==old else node
        value=replace(value)
        value['evidence']=[dict(id=ref,clauseId=ref,documentVersionId=version,documentSha256=byte_digest(raw),sourceUrl='https://example.invalid/protocol',locator=canonical_json(json.loads(clause['locator_json'])),quote=clause['text'],quoteSha256=byte_digest(clause['text'].encode()))]
        value['documentVersionIds']=[version];value['termRevisionIds']=[revision]
        graph=value['authorityGraph'];authority=graph['authorities'][0]
        authority['documentVersionIds']=[version];authority['documentSha256s']=[byte_digest(raw)]
        graph['members']=[dict(sha256=byte_digest(raw),bytes=len(raw),decodedBytes=len(raw),encoding='identity',kind='source_document')]
        graph['completedPeriod']['sourceSnapshotSha256']=byte_digest(raw)
        core={'run_date':run_date,'sections':{'Savings':{'rates':[]}}}
        details={'run_date':run_date,'products':{scope['productKey']:{'name':'Technical savings only','features':[]}}}
        def asset_bytes(kind,decoded):
            if adopted_assets is None:return _gzip_bytes(decoded)
            import gzip
            raw,expected=adopted_assets[kind]
            assert byte_digest(raw)==expected, 'Retained technical asset hash differs'
            assert json.loads(gzip.decompress(raw))==decoded, 'Retained technical asset content differs'
            return raw
        value['routing'].update(sourceGenerationId=finalized['generation_id'],exportContractSha256=finalized['export_contract_digest'],runDate=run_date,
            coreAssetSha256=store.put_blob(asset_bytes('core',core)),detailsAssetSha256=store.put_blob(asset_bytes('details',details)),productRecordSha256=digest(details['products'][scope['productKey']]))
        capture={'schema_version':1,'status':'CAPTURED_AND_QUEUED','products':1,'generation_id':finalized['generation_id'],'source_run_date':run_date,
            'export_contract_digest':finalized['export_contract_digest'],'source_provenance':{'basis':'finalized_source_generation','contract_sha256':store.put_blob((state/finalized['export_contract_path']).read_bytes()),'contract_digest':finalized['export_contract_digest']},
            'sources':[{'observation_id':observation,'product_key':scope['productKey'],'sha256':byte_digest(raw)}]}
        with store.db:store.db.execute('INSERT INTO ingest_captures VALUES(?,?,?,?)',(finalized['generation_id'],store.put_blob(canonical_json(capture).encode()),now,1))
        yield store,reidentify(value),observation
