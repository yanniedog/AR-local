const assert=require('node:assert/strict');
const {test}=require('node:test');
const {decode}=require('../../dashboard/history-transport.js');
function fixture(){return {format:'ar-dashboard-history-dictionary-v1',columns:['__proto__','rate','unknown'],values:['literal','0.0100',null,'2001-01-01','1'],templates:[[0,1,2],[0,1,-1]],observations:[[0,3,-1],[1,3,4]],row_count:2,run_dates:['2001-01-01'],section:'Savings',carry_forward_count:1};}
test('null, absence, decimals and prototype-named fields remain exact',()=>{
  const value=decode(fixture());
  assert.equal(value.rates[0].rate,'0.0100');assert.equal(value.rates[0].unknown,null);
  assert.equal(Object.hasOwn(value.rates[1],'unknown'),false);assert.equal(value.rates[1].carry_forward,'1');
  assert.equal(Object.hasOwn(value.rates[0],'carry_forward'),false);
  assert.equal(Object.getPrototypeOf(value.rates[0]),Object.prototype);
  assert.equal(Object.getOwnPropertyDescriptor(value.rates[0],'__proto__').value,'literal');
  value.rates[0].rate='changed';assert.equal(value.rates[1].rate,'0.0100');
});
test('malformed shape, references, limits and fallback responses fail closed',()=>{
  for(const mutate of [p=>p.format='future',p=>p.rates=[],p=>p.row_count=3,p=>p.templates[0][1]=99,p=>p.observations[0][0]=-1,p=>p.observations[0][1]=0.5,p=>p.columns.push('rate'),p=>p.values.push({}),p=>p.values.push(NaN),p=>p.columns[0]='run_date',p=>p.observations.length=1000001,p=>p.run_dates=['2001-02-30'],p=>p.carry_forward_count=0,p=>p.section='Other']){
    const value=fixture();mutate(value);assert.throws(()=>decode(value),/Invalid or oversized/);
  }
});
test('requested section binding cannot be relaxed',()=>assert.throws(()=>decode(fixture(),'Mortgage')));
test('empty history is complete and explicit',()=>{
  const value=fixture();Object.assign(value,{columns:[],values:[],templates:[],observations:[],row_count:0,carry_forward_count:0});
  assert.deepEqual(decode(value).rates,[]);
});
