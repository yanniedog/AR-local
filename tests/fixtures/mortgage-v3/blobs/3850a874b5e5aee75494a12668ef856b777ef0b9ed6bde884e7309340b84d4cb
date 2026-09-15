import { canonical, hashText } from '../../lib/productTermsEngine/validation';
import type { Fact, Facts, Rule } from '../../lib/productTermsEngine/types';
import { own, validFact, type CustomerProfile, type InputDefinition } from '../customerProfile';
import { customerInputRequirements, type CustomerInputContract } from '../customerInputRequirements';
import type { MortgageSubject, MortgageInputs, MortgageBinding } from './types';
export const mortgageAnswerId = (s: MortgageSubject, field: string) => `mort_${hashText(canonical([s.id,field]))}`;
export function mortgageDefinition(s: MortgageSubject, field: string): InputDefinition { const d = s.policy.inputDefinitions.find(d => d.field === field); if (!d) throw new Error('Mortgage input undeclared'); return { id:mortgageAnswerId(s,field),label:d.label,type:d.type,...(d.unit ? { unit:d.unit } : {}) }; }
export function mortgageFacts(s: MortgageSubject, inputs: MortgageInputs, profile: CustomerProfile) {
 const facts: Facts = Object.create(null), customerAnswers: CustomerProfile['answers'] = Object.create(null);
 const scenario: Partial<Record<MortgageBinding,Fact>> = { opening_principal:{type:'decimal',value:inputs.openingComponents.principal,unit:'AUD'},obligation_amount:{type:'decimal',value:inputs.obligationAmount,unit:'AUD'},from_date:{type:'date',value:inputs.from},to_exclusive_date:{type:'date',value:inputs.toExclusive},confirmed_annual_rate:{type:'decimal',value:inputs.confirmedAnnualRate,unit:'fraction'} };
 for (const [binding,key] of [['offer_purpose','purpose'],['offer_security','security'],['repayment_type','repaymentType']] as const) { const value = inputs.confirmedOfferFacts[key]; if (value !== undefined) scenario[binding] = {type:'text',value}; }
 for (const d of s.policy.inputDefinitions) {
  let value: Fact | undefined;
  if (d.binding !== 'customer_fact') value = scenario[d.binding];
  else {
   const direct = inputs.customerFacts.find(f => f.field === d.field), id = mortgageAnswerId(s,d.field), a = own(profile.answers,id) ? profile.answers[id] : undefined;
   if (direct) { if (direct.state === 'known' && direct.value) value = direct.value; }
   else if (a) { customerAnswers[id] = a; if (a.state === 'known' && a.provenance.productKey === s.scope.productKey && (!a.provenance.effectiveFrom || inputs.from >= a.provenance.effectiveFrom) && (!a.provenance.effectiveToExclusive || inputs.toExclusive <= a.provenance.effectiveToExclusive)) value = a.fact; }
  }
  if (value && validFact(value) && value.type === d.type && (value.type !== 'decimal' || value.unit === d.unit)) facts[d.field] = value;
 }
 return {facts,customerAnswers};
}
export function mortgageRequirements(s: MortgageSubject, inputs: MortgageInputs, profile: CustomerProfile) {
 const {facts,customerAnswers} = mortgageFacts(s,inputs,profile), rule = JSON.parse(canonical(s.policy.eligibility)) as Rule;
 function map(r: Rule) { if (r.op === 'compare') r.field = mortgageAnswerId(s,r.field); else if (r.op === 'not') map(r.rule); else if (r.op === 'and' || r.op === 'or') r.rules.forEach(map); } map(rule);
 const contract: CustomerInputContract = {schemaVersion:1,productKey:s.scope.productKey,revisionSha256:s.id,effectiveFrom:s.scope.from,effectiveToExclusive:s.scope.toExclusive,inputs:s.policy.inputDefinitions.map(d => mortgageDefinition(s,d.field)),rule};
 const mapped: Facts = Object.create(null); for (const [key,value] of Object.entries(facts)) mapped[mortgageAnswerId(s,key)] = value;
 const result = customerInputRequirements(contract,{...profile,answers:customerAnswers},s.scope.productKey,inputs.from,mapped);
 const deferred = new Set(inputs.customerFacts.filter(f => f.state === 'unavailable' || f.state === 'not_applicable').map(f => mortgageAnswerId(s,f.field)));
 return {facts,needed:result.needed.filter(d => !deferred.has(d.id)),deferred:[...result.deferred,...result.needed.filter(d => deferred.has(d.id))],saved:s.policy.inputDefinitions.filter(d => d.binding === 'customer_fact' && own(customerAnswers,mortgageAnswerId(s,d.field))).map(d => mortgageDefinition(s,d.field))};
}
