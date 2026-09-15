"""Current routing and historical source authority are independently verified."""
import gzip
import io
import json
from decimal import Decimal
from datetime import date
from .identity import canonical_json,digest
from .observation_checks import current_observation,selected_check
from .executable_sources import finalized_capture
from .executable_v3_contract import validate_subject
from .executable_v3_evidence import evidence_checked,evidence_operation,MAX_MEMBER
from .revisions import APPLICABILITY_FIELDS


def _json(operation,identity,compressed=False):
    key=(identity,compressed)
    cache=getattr(operation,'json_cache',{})
    if key in cache:return cache[key]
    prior=operation.decoded.get(identity)
    if prior:
        if prior[2]!=compressed:raise ValueError('Monetary JSON encoding differs')
        body=prior[1]
    else:
        raw=operation.read_blob(identity)
        if compressed:
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:body=stream.read(MAX_MEMBER+1)
        else:body=raw
        if len(body)>MAX_MEMBER or operation.decoded_bytes+len(body)>24*1024*1024:
            raise ValueError('Monetary JSON decoded budget exceeded')
        operation.decoded_bytes+=len(body)
        operation.decoded[identity]=(None,body,compressed)
    value=json.loads(body)
    cache[key]=value;operation.json_cache=cache
    return value


def _capture(operation,generation,run_date):
    key=(generation,run_date)
    if key not in operation.captures:
        if len(operation.captures)>=366:raise ValueError('Monetary capture count exceeded')
        operation.captures[key]=finalized_capture(operation,generation,run_date)
    return operation.captures[key]


def validate_destination(subject,core,details,core_sha,details_sha):
    route=subject['routing'];key=subject['scope']['productKey']
    if route['coreAssetSha256']!=core_sha or route['detailsAssetSha256']!=details_sha or core.get('run_date')!=route['runDate'] or details.get('run_date')!=route['runDate']:
        raise ValueError('Monetary current adopted assets differ')
    record=details.get('products',{}).get(key)
    if not isinstance(record,dict) or digest(record)!=route['productRecordSha256']:
        raise ValueError('Monetary current details record differs')


def _routing(store,subject,operation):
    route=subject['routing'];key=subject['scope']['productKey']
    current=current_observation(store,key)
    if current['ingest_id']!=route['sourceGenerationId']:
        raise ValueError('Monetary current routing generation changed')
    capture=_capture(operation,current['ingest_id'],route['runDate'])
    if (capture['export_contract_digest']!=route['exportContractSha256']
        or (current['observation_id'],key,current['source_sha256']) not in capture['_verified_members']):
        raise ValueError('Monetary current routing capture differs')
    source=_json(operation,current['source_sha256'])
    record=source.get('data',source) if isinstance(source,dict) else None
    if not isinstance(record,dict) or record.get('productCategory')!='TRANS_AND_SAVINGS_ACCOUNTS':
        raise ValueError('Monetary routing Savings category unproven')
    core=operation.adopted_json(route['coreAssetSha256']);details=operation.adopted_json(route['detailsAssetSha256'])
    validate_destination(subject,core,details,route['coreAssetSha256'],route['detailsAssetSha256'])
    return current


def _historical_snapshot(store,subject,snapshot,operation):
    row=store.db.execute('SELECT * FROM observations WHERE observation_id=?',(snapshot['observationId'],)).fetchone()
    if row is None or row['product_key']!=subject['scope']['productKey'] or any(row[k]!=snapshot[v] for k,v in (
        ('ingest_id','generationId'),('source_sha256','rawSourceSha256'),('observed_at','observedAt'))):
        raise ValueError('Monetary retained observation identity differs')
    manifest=_json(operation,snapshot['manifestSha256'])
    run_date=manifest.get('run_date')
    capture=_capture(operation,snapshot['generationId'],run_date)
    if (capture['export_contract_digest']!=snapshot['exportContractSha256'] or manifest.get('enc')
        or (snapshot['observationId'],row['product_key'],snapshot['rawSourceSha256']) not in capture['_verified_members']
        or manifest.get('source_observation',{}).get('generation_id')!=snapshot['generationId']
        or manifest.get('source_observation',{}).get('contract_digest')!=snapshot['exportContractSha256']):
        raise ValueError('Monetary historical finalized capture differs')
    decoded={}
    for kind,field in (('core','coreAssetSha256'),('details','detailsAssetSha256')):
        descriptor=manifest['files'][kind]
        if descriptor['sha256']!=snapshot[field] or descriptor['bytes']!=len(operation.read_blob(snapshot[field])) or descriptor.get('enc'):
            raise ValueError('Monetary historical asset descriptor differs')
        decoded[kind]=_json(operation,snapshot[field],True)
        if decoded[kind].get('run_date')!=run_date:raise ValueError('Monetary historical asset date differs')
    product=decoded['details'].get('products',{}).get(row['product_key'])
    if not isinstance(product,dict) or digest(product)!=snapshot['productRecordSha256']:
        raise ValueError('Monetary historical product record differs')
    rates=decoded['core'].get('sections',{}).get('Savings',{}).get('rates',[])
    if not isinstance(rates,list) or len(rates)>200000:raise ValueError('Monetary historical rows invalid')
    selected=[]
    for binding in snapshot['rateRows']:
        index=binding['coreRowIndex']
        if index>=len(rates):raise ValueError('Monetary historical row missing')
        item=rates[index]
        if item.get('product_key')!=row['product_key'] or item.get('rate_index')!=binding['rateIndex'] or digest(item)!=binding['rowSha256']:
            raise ValueError('Monetary historical exact row differs')
        selected.append(item)
    return dict(row),selected


def _revisions(store,subject,operation):
    result={};scope=subject['scope']
    for identity in subject['termRevisionIds']:
        row=store.db.execute('SELECT t.*,o.product_key FROM term_revisions t JOIN observations o USING(observation_id) WHERE term_revision_id=?',(identity,)).fetchone()
        review=store.db.execute('SELECT * FROM reviews WHERE term_revision_id=? ORDER BY sequence DESC LIMIT 1',(identity,)).fetchone()
        if row is None or review is None or review['status']!='validated' or row['product_key']!=scope['productKey']:
            raise ValueError('Monetary historical revision no longer validated')
        operation.read_blob(review['evidence_sha256'])
        applicability=json.loads(row['applicability_json'])
        if set(applicability)!=APPLICABILITY_FIELDS or any(applicability[k]!=scope[v] for k,v in (
            ('product_key','productKey'),('cohort','cohortKey'),('tier','tierKey'),('package','packageKey'))):
            raise ValueError('Monetary historical revision scope differs')
        for endpoint in ('effective_from','effective_to'):
            value=applicability[endpoint]
            if value is not None:
                if not isinstance(value,str) or len(value)!=10:raise ValueError('Monetary reviewed date precision invalid')
                date.fromisoformat(value)
        sources={x[0] for x in store.db.execute('SELECT clause_id FROM term_sources WHERE term_revision_id=?',(identity,))}
        used_until=[]
        for authority in subject['authorityGraph']['authorities']:
            for coverage in authority['fieldCoverage']:
                if not sources.intersection(coverage['evidenceIds']):continue
                for period in subject['policy']['intervals']:
                    lower=max(coverage['from'],period['from']);upper=min(coverage['toExclusive'],period['toExclusive'])
                    if period['authorityId']==authority['id'] and lower<upper:used_until.append(upper)
        _historical_changes(store,identity,scope,operation,max(used_until,default=scope['from']))
        result[identity]={'row':dict(row),'review':dict(review),'applicability':applicability,'clauses':sources}
    return result


def _historical_changes(store,identity,scope,operation,used_until):
    """A reviewed later policy is not a retrospective correction of this horizon."""
    changes=store.db.execute('SELECT * FROM term_changes WHERE before_revision_id=? LIMIT 513',(identity,)).fetchall()
    if len(changes)>512:raise ValueError('Monetary revision change inventory bound exceeded')
    for change in changes:
        if change['kind']!='changed':raise ValueError('Monetary historical revision no longer validated')
        after=store.db.execute('SELECT t.*,r.status,r.evidence_sha256 FROM term_revisions t JOIN reviews r '
            'ON r.sequence=(SELECT MAX(sequence) FROM reviews WHERE term_revision_id=t.term_revision_id) '
            'WHERE t.term_revision_id=?',(change['after_revision_id'],)).fetchone()
        applicability=json.loads(after['applicability_json']) if after else {}
        lower=applicability.get('effective_from');upper=applicability.get('effective_to')
        if (after is None or after['status']!='validated' or set(applicability)!=APPLICABILITY_FIELDS
            or any(applicability[k]!=scope[v] for k,v in (('product_key','productKey'),('cohort','cohortKey'),('tier','tierKey'),('package','packageKey')))
            or not isinstance(lower,str) or len(lower)!=10 or lower<used_until):
            raise ValueError('Monetary historical revision no longer validated')
        date.fromisoformat(lower)
        if upper is not None:
            if not isinstance(upper,str) or len(upper)!=10 or date.fromisoformat(upper)<=date.fromisoformat(lower):
                raise ValueError('Monetary successor applicability invalid')
        operation.read_blob(after['evidence_sha256'])
        proof=_json(operation,json.loads(change['evidence_json'])['evidence_sha256'])
        if (proof.get('passed') is not True or proof.get('kind')!='changed'
            or proof.get('before_revision_id')!=identity or proof.get('after_revision_id')!=change['after_revision_id']):
            raise ValueError('Monetary successor change evidence differs')
        sources=store.db.execute('SELECT x.status,v.content_sha256 FROM term_sources s JOIN clauses c USING(clause_id) '
            'JOIN extractions x USING(extraction_id) JOIN document_versions v USING(document_version_id) '
            'WHERE s.term_revision_id=? LIMIT 513',(change['after_revision_id'],)).fetchall()
        if not sources or len(sources)>512 or any(x['status']!='complete' for x in sources):
            raise ValueError('Monetary successor source evidence incomplete')
        original={x[0] for x in store.db.execute('SELECT v.content_sha256 FROM term_sources s JOIN clauses c USING(clause_id) '
            'JOIN extractions x USING(extraction_id) JOIN document_versions v USING(document_version_id) WHERE s.term_revision_id=?',(identity,))}
        if {x['content_sha256'] for x in sources}==original:
            raise ValueError('Monetary unchanged sources cannot establish a later policy')
        for source in sources:operation.read_blob(source['content_sha256'])


def _clauses(store,subject,revisions,operation):
    known={}
    allclauses=set().union(*(x['clauses'] for x in revisions.values()))
    for evidence in subject['evidence']:
        row=store.db.execute('SELECT c.*,x.document_version_id,x.status AS extraction_status,v.content_sha256,v.document_id,v.byte_size,d.source_url '
            'FROM clauses c JOIN extractions x USING(extraction_id) JOIN document_versions v USING(document_version_id) '
            'JOIN documents d USING(document_id) WHERE clause_id=?',(evidence['clauseId'],)).fetchone()
        if row is None or row['extraction_status']!='complete' or evidence['clauseId'] not in allclauses:
            raise ValueError('Monetary clause lacks reviewed complete extraction')
        expected={'documentVersionId':row['document_version_id'],'documentSha256':row['content_sha256'],
            'sourceUrl':row['source_url'],'locator':canonical_json(json.loads(row['locator_json'])),'quote':row['text']}
        if any(evidence[k]!=v for k,v in expected.items()) or len(operation.read_blob(row['content_sha256']))!=row['byte_size']:
            raise ValueError('Monetary original clause/document bytes differ')
        known[evidence['id']]=dict(row)
    return known


@evidence_checked
def source_snapshot(store,subject):
    validate_subject(subject)
    with evidence_operation(store) as operation:
        operation.admit(subject)
        routing=_routing(store,subject,operation)
        revisions=_revisions(store,subject,operation);clauses=_clauses(store,subject,revisions,operation)
        history={}
        for authority in subject['authorityGraph']['authorities']:
            if authority['kind']=='retained_observation':
                for snapshot in authority['observations']:
                    observation,rows=_historical_snapshot(store,subject,snapshot,operation)
                    history[observation['observation_id']]=observation
                    for interval in subject['policy']['intervals']:
                        if interval['authorityId']==authority['id'] and any(not any(Decimal(str(row.get('rate')))==Decimal(tier['annualRate']) for row in rows) for tier in interval['tiers']):
                            raise ValueError('Monetary rate not present in exact historical rows')
            else:
                selected=[clauses[x] for x in authority['datedRateAndPolicyClauseIds']]
                if set(authority['documentVersionIds'])!={x['document_version_id'] for x in selected} or set(authority['documentSha256s'])!={x['content_sha256'] for x in selected}:
                    raise ValueError('Monetary dated-clause document inventory differs')
            for coverage in authority['fieldCoverage']:
                for clause in coverage['evidenceIds']:
                    supporting=[r for r in revisions.values() if clause in r['clauses']]
                    if not any(isinstance(r['applicability']['effective_from'],str) and isinstance(r['applicability']['effective_to'],str)
                        and len(r['applicability']['effective_from'])==10 and len(r['applicability']['effective_to'])==10
                        and r['applicability']['effective_from']<=coverage['from']<coverage['toExclusive']<=r['applicability']['effective_to'] for r in supporting):
                        raise ValueError('Monetary field lacks independently reviewed dated applicability')
        # Exact current review and source inventories participate, so correction/revocation invalidates reuse.
        return digest({'subject':subject['id'],'routing':routing,'historicalObservations':history,
            'reviews':{k:r['review'] for k,r in revisions.items()},'authorityGraph':subject['authorityGraph']['identitySha256']})
