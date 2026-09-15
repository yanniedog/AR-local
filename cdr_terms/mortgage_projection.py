"""Exact private adapter projection, independently checked against retained calls."""
from .identity import digest
from .mortgage_inputs import check_inputs,component,fixed


def unique(values):return list(dict.fromkeys(values))


def projection(s,i,binding,approval,facts):
    obligations=check_inputs(s,i);p=s['policy'];refs=p['fieldEvidenceIds'];category='mortgage_fees_'+s['id'][:20]
    orders={f['id']:n for n,f in enumerate(sorted(p['fees']['occurrences'],key=lambda f:(f['dueDate'],f['order'])))}
    technical='mortfee_'+digest([s['id'],i['accountId']])[:24];fees=[]
    for f in p['fees']['occurrences']:
        account=next((a['accountId'] for a in i['externalAccounts'] if a['role']==f['externalAccountRole']),technical)
        fees.append(dict(id=f['id'],chargeIdentity=digest([s['id'],'fee',f['id']]),categoryId=category,evidenceIds=f['evidenceIds'],scope=dict(type='account',accountId=i['accountId']),
            timing=dict(type='dated',**{'from':i['from'],'toExclusive':i['toExclusive']},triggerCoverage='reviewed_complete',occurrences=[dict(incurredDate=f['incurredDate'],dueDate=f['dueDate'],triggerId=f['id'])]),
            order=orders[f['id']],debit=dict(type='external_account',accountId=account),price=dict(type='fixed',value=f['amount']),applicability=None,waiver=None,discounts=[],discountPrecedence='exclusive',discountRounding='half_up'))
    contract=dict(schemaVersion=1,evaluatorVersion='product-terms-engine-v8',id=s['id'],productId=s['scope']['productKey'],direction='liability',currency='AUD',
        review=dict(applicability='verified',materialTerms='verified',feeCoverage='verified',rateSchedule='verified',benchmarkSha256=approval['benchmarkResultSha256']),
        applicability=dict(cohortKey=s['scope']['cohortKey'],**{'from':i['from'],'toExclusive':i['toExclusive']}),evidence=s['evidence'],
        dependencyIds=unique([*[binding[k] for k in ('manifestSha256','edition','indexSha256','shardSha256','assetSha256','coreSha256','detailsSha256','authorityGraphSha256')],*s['documentVersionIds'],*s['termRevisionIds']]),unsupportedTerms=[],eligibility=p['eligibility'],initialAnnualRate=p['annualRate'],initialRateEvidenceIds=refs['rates'],
        interest=dict(dayCount=p['dayCount'],balanceBasis='loan_declared_component_basis',eventOrder='loan_declared_payment_phase_then_posting',dailyRateRounding=p['dailyRateRounding'],dailyAccrualScale=p['dailyAccrualScale'],
            accrualRounding=p['accrualRounding'],postingRounding=p['postingRounding'],postingDates=p['postingInventory']['dueDates'],offset='none',
            evidenceIds=unique(x for k in ('interestBasis','dayCount','dailyRateRounding','dailyAccrualRounding','postingRounding','postingResidue','postingDates') for x in refs[k])),
        feeSchedule=dict(schemaVersion=1,accountId=i['accountId'],**{'from':i['from'],'toExclusive':i['toExclusive']},inventoryCoverage='reviewed_complete',deferredObligations='none_confirmed',evidenceIds=refs['feeInventory'],
            inventory=[dict(categoryId=category,state='scheduled' if fees else 'none_applicable',feeIds=[f['id'] for f in fees],evidenceIds=refs['feeInventory'])],ordering=p['fees']['ordering'],fees=fees))
    contract['loanContract']=dict(schemaVersion=1,accountId=i['accountId'],cohortKey=s['scope']['cohortKey'],offerId=i['offerId'],sourceVersion=i['sourceVersion'],**{'from':i['from'],'toExclusive':i['toExclusive']},
        evidenceIds=unique(x for k in ('interestBasis','allocation','paymentPhase','paymentRounding','accruedSettlement') for x in refs[k]),
        opening=dict(effectiveDate=i['from'],snapshotId=i['snapshotId'],outstanding=i['openingOutstanding'],components=i['openingComponents'],redrawAvailable='0',evidenceIds=refs['openingState']),
        interestBearing=p['interestBearing'],allocation=p['allocation'],paymentTiming=p['paymentPhase'],overpayment='reject',paymentRounding=p['paymentRounding'],accruedSettlement=p['accruedSettlement'],
        advancesTiming='start_of_day_before_fees',feeBalanceBasis='outstanding_including_unposted',obligationMeasurement='before_payment_phase',reversalPolicy='unknown',scheduleCoverage='reviewed_complete',obligations=obligations,advances=[],rates=[],
        extraPayments=dict(allowed=False,totalCap='0',increasesRedraw=False,evidenceIds=refs['excludedPeriodEffects']),redraw=dict(allowed=False,totalCap='0',evidenceIds=refs['excludedPeriodEffects']),feeFunding=[],offset=None,closure=None)
    scenario=dict(accountId=i['accountId'],productId=s['scope']['productKey'],cohortKey=s['scope']['cohortKey'],startDate=i['from'],endDateExclusive=i['toExclusive'],openingBalance=fixed(component(i['openingOutstanding']),12),initialOffset='0',facts=facts,events=[],assumptions=[],
        loan=dict(offerId=i['offerId'],sourceVersion=i['sourceVersion'],openingSnapshotId=i['snapshotId'],mode='cleared',executions=[dict(id=e['id'],accountId=e['accountId'],date=e['date'],order=e['order'],status='cleared',type='payment',amount=e['amount'],obligationId=e['obligationId'],evidenceIds=refs['paymentPhase']) for e in i['payments']]))
    return dict(contract=contract,scenario=scenario)
