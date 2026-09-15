"""Mortgage selected intervals and material/event authority coverage."""
from .executable_v3_graph import validate_inventory,_covers
from .mortgage_contract import periods
from .mortgage_material_fields import GROUPS


def validate_graph(subject):
    authorities=validate_inventory(subject);policy=subject['policy'];scope=subject['scope']
    segments=periods(subject);relations=subject['authorityGraph']['supersessions']
    for relation in relations:
        a=authorities.get(relation['selectedAuthorityId']);b=authorities.get(relation['supersededAuthorityId'])
        if a is None or b is None or a['id']==b['id'] or not max(a['from'],b['from'])<=relation['from']<relation['toExclusive']<=min(a['toExclusive'],b['toExclusive']):
            raise ValueError('Mortgage supersession interval differs')
    if set(policy['fieldEvidenceIds'])!=set(GROUPS):raise ValueError('Mortgage material field inventory differs')
    postings=policy['postingInventory']['dueDates'];fees=policy['fees']['occurrences']
    for field in GROUPS:
        required=set(policy['fieldEvidenceIds'][field]);entries=[]
        for segment in segments:
            for entry in authorities[segment['authorityId']]['fieldCoverage']:
                if entry['field']!=field or not set(entry['evidenceIds'])&required:continue
                lower=max(segment['from'],entry['from']);upper=min(segment['toExclusive'],entry['toExclusive'])
                if lower<upper:entries.append({**entry,'from':lower,'toExclusive':upper})
        if not _covers([(e['from'],e['toExclusive']) for e in entries],scope['from'],scope['toExclusive']) or not required<=set(r for e in entries for r in e['evidenceIds']):
            raise ValueError('Mortgage material field coverage gap')
        events=postings if field in {'interestBasis','postingDates','postingResidue','postingRounding'} else [d for f in fees for d in (f['incurredDate'],f['dueDate'])] if field=='feeInventory' else [f['dueDate'] for f in fees] if field=='feeSettlement' else []
        if any(not any(e['from']<=d<e['toExclusive'] and d in e['postingEventDates'] for e in entries) for d in events):
            raise ValueError('Mortgage source event coverage gap')
    # Private anchor-specific due events are checked again by the benchmark adapter projection.
