"""Technical protocol controls only; these subjects have no banking approval."""
import copy

from cdr_terms.executable_v2_contract import scope_identity
from cdr_terms.identity import digest


def subject_from_template(template):
    old = copy.deepcopy(template)
    scope = {key: old[key] for key in ('productKey', 'cohortKey', 'tierKey', 'packageKey',
                                     'effectiveFrom', 'effectiveToExclusive')}
    scope.update(family='TD', effectiveScope='assessment_date', intervalBasis='reviewed_assessment_coverage',
                 coverage='rate_variants', rateIndexes=[old['selectedRate']['rateIndex']])
    source = {new: old[previous] for new, previous in (
        ('observationId', 'sourceObservationId'), ('sourceSha256', 'sourceSha256'),
        ('generationId', 'sourceGenerationId'), ('runDate', 'runDate'),
        ('documentVersionIds', 'documentVersionIds'), ('termRevisionIds', 'termRevisionIds'))}
    source.update(exportContractSha256='a' * 64, detailsAssetSha256='b' * 64,
                  productRecordSha256='c' * 64,
                  provenanceManifestSha256=old['selectedRate']['sourceManifestSha256'],
                  coreAssetSha256=old['selectedRate']['coreAssetSha256'],
                  rateRows=[{k: old['selectedRate'][k] for k in ('coreRowIndex', 'rateIndex', 'rowSha256')}])
    inputs = old['inputDefinitions'][:2]
    inputs[0]['binding'] = 'scenario_amount'
    inputs[1]['binding'] = 'assessment_date'
    subject = dict(schemaVersion=2, kind='scoped_eligibility_v1', capability='eligibility_only',
        adapterVersion='scoped-eligibility-v1', evaluatorVersion='product-terms-engine-v8',
        scope=scope, source=source, inputDefinitions=inputs, eligibility=old['eligibility'], evidence=old['evidence'],
        fieldClauseIds={key: [old['evidence'][0]['clauseId']] for key in
            ('product', 'family', 'cohort', 'tier', 'package', 'effectiveInterval', 'effectiveScope', 'coverage', 'eligibility')})
    return reidentify(subject)


def reidentify(subject):
    subject['scopeId'] = scope_identity(subject)
    subject['id'] = digest({k: v for k, v in subject.items() if k != 'id'})
    return subject
