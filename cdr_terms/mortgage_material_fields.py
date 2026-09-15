"""Closed reviewed mortgage material; original evidence remains private."""
import copy,json,hashlib
from pathlib import Path
from datetime import date
from jsonschema import Draft202012Validator,FormatChecker
from referencing import Registry,Resource
SCHEMA=Path(__file__).resolve().parents[1]/'contracts/product_terms/drafts/material-fields-v2/mortgage-field.schema.json'

def validate_field_value(value):
 from .executable_contract import _bounded
 from .parameter_registry import MORTGAGE_FIELD_SHA
 _bounded(value,256*1024)
 raw=SCHEMA.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=MORTGAGE_FIELD_SHA:raise ValueError('Mortgage material schema identity differs')
 from .executable_v2_contract import _offline
 definition=json.loads((SCHEMA.parents[2]/'monetary-v3/mortgage/definitions.schema.json').read_bytes())
 registry=Registry(retrieve=_offline).with_resource(definition['$id'],Resource.from_contents(definition))
 common=json.loads((SCHEMA.parents[2]/'monetary-v3/schemas/common.schema.json').read_bytes())
 registry=registry.with_resource(common['$id'],Resource.from_contents(common))
 Draft202012Validator(json.loads(raw),registry=registry,format_checker=FormatChecker()).validate(value)
 if date.fromisoformat(value['from'])>=date.fromisoformat(value['toExclusive']):raise ValueError('Mortgage material interval invalid')
GROUPS={
 'rates':['currency','annualRate'],
 'interestBasis':['interestBearing'],
 'allocation':['allocation'],
 'paymentPhase':['paymentPhase'],
 'paymentRounding':['paymentRounding'],
 'accruedSettlement':['accruedSettlement'],
 'dayCount':['dayCount'],
 'dailyRateRounding':['dailyRateRounding'],
 'dailyAccrualRounding':['dailyAccrualScale','accrualRounding'],
 'postingRounding':['postingRounding'],
 'postingResidue':['postingResidue'],
 'postingDates':['postingInventory'],
 'obligationCalendar':['obligationCalendar'],
 'openingState':['openingState'],
 'feeInventory':['fees'],
 'feeSettlement':['fees'],
 'excludedPeriodEffects':['excludedPeriodEffects','mode','maxHorizonDays'],
 'eligibility':['eligibility','inputDefinitions'],
}
# Units and adapter limits are semantic values, not provenance; bind them explicitly.
EXTRA={
 'rates':{'rateUnit':'fraction_per_year'},
 'interestBasis':{'balanceBasis':'loan_declared_component_basis','currency':'AUD'},
 'allocation':{'overpayment':'reject'},
 'paymentPhase':{'eventOrder':'loan_declared_payment_phase_then_posting','obligationMeasurement':'before_payment_phase'},
 'paymentRounding':{'amountUnit':'AUD','scale':2},
 'accruedSettlement':{'amountUnit':'AUD','scale':2},
 'dailyRateRounding':{'annualRateUnit':'fraction_per_year'},
 'dailyAccrualRounding':{'amountUnit':'AUD'},
 'postingRounding':{'amountUnit':'AUD','scale':2},
 'postingResidue':{'amountUnit':'AUD'},
 'openingState':{'accruedMaximumScale':12,'otherComponentMaximumScale':2,'outstandingMaximumScale':12,'reconciliation':'exact_sum','provenance':'user_reported_bank_offer_and_statement'},
 'feeInventory':{'currency':'AUD','incurrenceAdmission':'period_start_lte_incurred_lte_due_lt_period_end','orderAdmission':'source_order_unique_per_due_date'},
 'feeSettlement':{'currency':'AUD','positiveFeeCash':'exact_cleared_due_date_amount_and_external_account','zeroFeeCash':'no_settlement_required'},
}
def semantic(x):
 if isinstance(x,list):return [semantic(v)for v in x]
 if isinstance(x,dict):return {k:semantic(v)for k,v in x.items()if k not in ('evidenceIds','completenessEvidenceIds','fieldEvidenceIds','authorityId')}
 return x

def project_field(subject,field):
 p=subject['policy'];value={k:semantic(copy.deepcopy(p[k]))for k in GROUPS[field]};value.update(EXTRA.get(field,{}));return value

def field_value(subject,field):
 return {'schemaVersion':1,'field':field,'scope':{k:subject['scope'][k]for k in ('productKey','cohortKey','tierKey','packageKey')},'from':subject['scope']['from'],'toExclusive':subject['scope']['toExclusive'],'material':project_field(subject,field)}
