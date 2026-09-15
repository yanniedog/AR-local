"""Bounded structured temporal authority graph checks, without asserting source truth."""
from datetime import date, timedelta
from .executable_v3_contract import identity, _range
from .executable_v2_contract import validate_review_time

FIELDS={'rates','allocation','dayCount','balanceBasis','eventOrder','dailyRateRounding','dailyAccrualRounding',
        'postingRounding','postingResidue','postingDates','postingDestination','depositSettlementBasis',
        'noBonusIntro','noOffsetLinkedAccounts','feeCoverage','noDeferredObligations','eligibility'}
POSTING_FIELDS={'postingRounding','postingResidue','postingDates','postingDestination','balanceBasis'}


def _covers(ranges,lower,upper):
    cursor=lower
    for start,end in sorted(ranges):
        if end<=cursor: continue
        if start>cursor: return False
        cursor=max(cursor,end)
        if cursor>=upper: return True
    return False


def validate_graph(subject):
    graph,scope=subject['authorityGraph'],subject['scope']
    if graph['identitySha256']!=identity(graph,'identitySha256'):
        raise ValueError('Monetary authority graph identity differs')
    members={}
    for member in graph['members']:
        if member['sha256'] in members: raise ValueError('Monetary duplicate member identity')
        members[member['sha256']]=member
    if sum(x['bytes'] for x in members.values())>32*1024*1024 or sum(x['decodedBytes'] for x in members.values())>24*1024*1024:
        raise ValueError('Monetary authority member operation bound exceeded')
    bound=graph['completedPeriod']; validate_review_time(bound['asOf'])
    if scope['toExclusive']>bound['completedThroughExclusive'] or bound['sourceSnapshotSha256'] not in members:
        raise ValueError('Monetary completed-period authority missing')
    authorities={}; observations=set(); documents=set(); used_members={bound['sourceSnapshotSha256']}
    for authority in graph['authorities']:
        if authority['id']!=identity(authority) or authority['id'] in authorities:
            raise ValueError('Monetary authority identity differs')
        authorities[authority['id']]=authority
        _range(authority['from'],authority['toExclusive'])
        other=authority['scope'];_range(other['from'],other['toExclusive'])
        if any(scope[k]!=other[k] for k in ('productKey','family','cohortKey','tierKey','packageKey','coverage')) or not other['from']<=authority['from']<authority['toExclusive']<=other['toExclusive']:
            raise ValueError('Monetary authority scope differs')
        for field in authority['fieldCoverage']:
            _range(field['from'],field['toExclusive'])
            if not authority['from']<=field['from']<field['toExclusive']<=authority['toExclusive']:
                raise ValueError('Monetary field coverage exceeds authority')
            if field['postingEventDates']!=sorted(set(field['postingEventDates'])) or any(not field['from']<=d<field['toExclusive'] for d in field['postingEventDates']):
                raise ValueError('Monetary posting event coverage invalid')
        if authority['kind']=='retained_observation':
            proof=authority['coverageProof']
            if proof['from']>authority['from'] or proof['toExclusive']<authority['toExclusive']:
                raise ValueError('Monetary observation coverage incomplete')
            observed_days=set()
            for snapshot in authority['observations']:
                validate_review_time(snapshot['observedAt'])
                observations.add(snapshot['observationId']);observed_days.add(snapshot['observedAt'][:10])
                used_members.update(snapshot[k] for k in ('manifestSha256','coreAssetSha256','detailsAssetSha256','rawSourceSha256'))
                rows=snapshot['rateRows']
                if len({r['coreRowIndex'] for r in rows})!=len(rows) or len({r['rateIndex'] for r in rows})!=len(rows):
                    raise ValueError('Monetary historical row inventory duplicates')
            if proof['basis']=='complete_daily_observations':
                start,end=_range(authority['from'],authority['toExclusive'])
                if (end-start).days>366 or not {(start+timedelta(days=n)).isoformat() for n in range((end-start).days)}<=observed_days:
                    raise ValueError('Monetary daily observation gap')
        else:
            documents.update(authority['documentVersionIds']);used_members.update(authority['documentSha256s'])
    documents.update(subject['documentVersionIds'])
    used_members.update(e['documentSha256'] for e in subject['evidence'])
    if len(observations)>366 or len(documents)>256 or used_members!=set(members):
        raise ValueError('Monetary missing/orphan authority members or bound exceeded')
    used=set()
    for period in subject['policy']['intervals']:
        selected=authorities.get(period['authorityId'])
        if selected is None or not selected['from']<=period['from']<period['toExclusive']<=selected['toExclusive']:
            raise ValueError('Monetary interval authority missing')
        used.add(selected['id'])
        for field in FIELDS:
            required=set(period['fieldEvidenceIds'].get(field,[]))
            if field=='eligibility':
                pending=[subject['policy']['eligibility']]
                while pending:
                    node=pending.pop();required.update(node.get('evidenceIds',[]))
                    pending.extend(node.get('rules',[]))
                    if 'rule' in node:pending.append(node['rule'])
            entries=[x for x in selected['fieldCoverage'] if x['field']==field
                and x['from']<period['toExclusive'] and period['from']<x['toExclusive'] and set(x['evidenceIds'])&required]
            if not required<=set(ref for x in entries for ref in x['evidenceIds']):
                raise ValueError('Monetary field coverage evidence incomplete')
            if not _covers([(x['from'],x['toExclusive']) for x in entries],period['from'],period['toExclusive']):
                raise ValueError('Monetary required field coverage missing')
            if field in POSTING_FIELDS and not set(period['interest']['postingDates'])<=set(d for x in entries for d in x['postingEventDates']):
                raise ValueError('Monetary required posting-event coverage missing')
        for candidate in authorities.values():
            lower=max(candidate['from'],period['from']);upper=min(candidate['toExclusive'],period['toExclusive'])
            if candidate['id']==selected['id'] or lower>=upper: continue
            supersessions=[s for s in graph['supersessions'] if s['supersededAuthorityId']==candidate['id'] and s['selectedAuthorityId']==selected['id']]
            if not _covers([(s['from'],s['toExclusive']) for s in supersessions],lower,upper):
                raise ValueError('Monetary conflicting authority lacks explicit supersession')
            used.add(candidate['id'])
    for item in graph['supersessions']:
        _range(item['from'],item['toExclusive'])
        if item['selectedAuthorityId'] not in authorities or item['supersededAuthorityId'] not in authorities or item['selectedAuthorityId']==item['supersededAuthorityId']:
            raise ValueError('Monetary supersession identities invalid')
    if used!=set(authorities): raise ValueError('Monetary unused authority')
