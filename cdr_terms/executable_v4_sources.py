"""Activity source admission through retained originals and typed reviewed fields."""
from decimal import Decimal
from .identity import digest
from .executable_v3_evidence import evidence_checked, evidence_operation
from .structured_contract import evidence_reads
from .executable_v3_sources import _routing, _revisions, _clauses, _historical_snapshot
from .executable_v4_contract import validate_subject
from .executable_v3_graph import _covers
from .monetary_material_fields import validate_material_coverage


def _historical_rates(subject, authority, rows):
    # Assessment-only periods consume activity policy, not a deposit-rate claim.
    for period in subject['policy']['intervals']:
        if period['authorityId'] != authority['id']: continue
        rates = [t['annualRate'] for t in period['tiers'] + subject['policy']['bonus']['tiers']]
        if any(not any(Decimal(str(row.get('rate'))) == Decimal(rate) for row in rows) for rate in rates):
            raise ValueError('Activity rate not present in exact historical rows')


def _coverage(store, subject, authority, revisions, operation):
    for coverage in authority['fieldCoverage']:
        validate_material_coverage(store, subject, authority, coverage, revisions, operation)
        for clause in coverage['evidenceIds']:
            supporting = [r for r in revisions.values() if clause in r['clauses']]
            ranges=[(r['applicability']['effective_from'],r['applicability']['effective_to']) for r in supporting
                    if isinstance(r['applicability']['effective_from'],str)
                    and isinstance(r['applicability']['effective_to'],str)
                    and len(r['applicability']['effective_from'])==10 and len(r['applicability']['effective_to'])==10]
            if not _covers(ranges,coverage['from'],coverage['toExclusive']):
                raise ValueError('Activity field lacks independently reviewed dated applicability')


@evidence_checked
@evidence_reads
def source_snapshot(store, subject):
    validate_subject(subject)
    with evidence_operation(store) as operation:
        operation.admit(subject)
        routing = _routing(store, subject, operation)
        details=operation.adopted_json(subject['routing']['detailsAssetSha256'])
        product=details['products'][subject['scope']['productKey']]
        if product.get('displayIdentity',{}).get('productCategory')!='TRANS_AND_SAVINGS_ACCOUNTS':
            raise ValueError('Activity adopted product category unsupported')
        revisions = _revisions(store, subject, operation)
        clauses = _clauses(store, subject, revisions, operation)
        history = {}
        for authority in subject['authorityGraph']['authorities']:
            if authority['kind'] == 'retained_observation':
                for snapshot in authority['observations']:
                    observation, rows = _historical_snapshot(store, subject, snapshot, operation)
                    history[observation['observation_id']] = observation
                    _historical_rates(subject, authority, rows)
            else:
                selected = [clauses[x] for x in authority['datedRateAndPolicyClauseIds']]
                if (set(authority['documentVersionIds']) != {x['document_version_id'] for x in selected}
                    or set(authority['documentSha256s']) != {x['content_sha256'] for x in selected}):
                    raise ValueError('Activity dated-clause document inventory differs')
            _coverage(store, subject, authority, revisions, operation)
        return digest({'subject': subject['id'], 'routing': routing, 'historicalObservations': history,
                       'reviews': {k: r['review'] for k, r in revisions.items()},
                       'authorityGraph': subject['authorityGraph']['identitySha256']})


def validate_destination(subject, core, details, core_sha, details_sha):
    from .executable_v3_sources import validate_destination as validate_base
    validate_base(subject, core, details, core_sha, details_sha)
    product = details['products'][subject['scope']['productKey']]
    if product.get('displayIdentity', {}).get('productCategory') != 'TRANS_AND_SAVINGS_ACCOUNTS':
        raise ValueError('Activity current details category unproven')
