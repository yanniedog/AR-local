import { utf8ToBytes } from '@noble/hashes/utils';
import { canonical, hashText } from '../../lib/productTermsEngine/validation';
import { calculateLedger } from '../../lib/productTermsEngine/ledger';
import type { CustomerProfile } from '../customerProfile';
import { MORTGAGE_ADAPTER, type MortgageInputs } from './types';
import { assertMortgageSelection, type MortgageContext, type MortgageSelection, type MortgageTarget } from './transport';
import { mortgageFacts, mortgageRequirements, mortgageAnswerId } from './facts';
import { assembleMortgage } from './assemble';
import { assertMortgageInputs } from './schemaValidation';
export function instantiateMortgagePeriod(selection: MortgageSelection, context: MortgageContext, target: MortgageTarget, inputs: MortgageInputs, profile: CustomerProfile) {
 const binding = assertMortgageSelection(selection,context,target); assertMortgageInputs(inputs);
 const s = selection.subject, {facts,customerAnswers} = mortgageFacts(s,inputs,profile), requirements = mortgageRequirements(s,inputs,profile);
 if (requirements.needed.some(d => s.policy.inputDefinitions.find(x => mortgageAnswerId(s,x.field) === d.id)?.binding !== 'customer_fact')) throw new Error('Mortgage relevant offer confirmation missing');
 const {contract,scenario} = assembleMortgage(s,selection.approval,inputs,facts,binding);
 const selectedTarget = target.kind === 'product' ? {kind:target.kind,productKey:target.productKey,productRecordSha256:s.routing.productRecordSha256} : {kind:target.kind,productKey:target.productKey,section:target.section,coreRowIndex:context.core!.sections[target.section].rates.indexOf(target.row),rateIndex:target.row.rate_index,rowSha256:hashText(canonical(target.row)),productRecordSha256:s.routing.productRecordSha256};
 const adapterInputs = JSON.parse(canonical({subject:s,approval:selection.approval,binding,target:selectedTarget,inputs,customerAnswers,facts}));
 if (utf8ToBytes(canonical(adapterInputs)).length > 512*1024) throw new Error('Mortgage private input limit');
 return {adapterInputs,contract,scenario};
}
export function calculateMortgagePeriod(selection: MortgageSelection, context: MortgageContext, target: MortgageTarget, inputs: MortgageInputs, profile: CustomerProfile) {
 const {adapterInputs,contract,scenario} = instantiateMortgagePeriod(selection,context,target,inputs,profile);
 const result = {schemaVersion:1,evaluationKind:'mortgage_calculation',adapterVersion:MORTGAGE_ADAPTER,evaluatorVersion:'product-terms-engine-v8',verificationScope:'Current publication and approved structured source policy verified on-device; original source bytes and typed material revisions verified by producer.',basis:'User-reported historical loan period. Obligations are separate from cleared payments; external fees are separate from loan cashflows. No credit approval or full portfolio comparison.',adapterInputs,inputSha256:hashText(canonical(adapterInputs)),calculationInputs:{contract,scenario},receipt:calculateLedger(contract,scenario)};
 if (utf8ToBytes(canonical(result)).length > 4*1024*1024) throw new Error('Mortgage receipt limit'); return result;
}
