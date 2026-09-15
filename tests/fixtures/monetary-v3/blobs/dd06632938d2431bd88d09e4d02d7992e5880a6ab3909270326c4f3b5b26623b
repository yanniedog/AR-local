import fs from 'fs';
import path from 'path';
import { execFileSync } from 'child_process';
import schemas, { eligibilitySchemas } from '../src/data/monetaryContracts/runtimeSchemas';
import { assertEligibilityWire } from '../src/data/eligibilityContracts/schemaValidation';
import { eligibilitySubject } from '../test-support/eligibilityHarness';
import { assertMonetaryWire } from '../src/data/monetaryContracts/schemaValidation';
import { savingsSubject } from '../test-support/savingsMonetaryHarness';
test('generated runtime graph reconstructs all eight frozen schemas and every reference exactly', () => {
  execFileSync(process.execPath, [path.resolve('scripts/generate-monetary-schemas.mjs'), '--check']);
  const byId: Record<string, any> = Object.fromEntries(Object.values(schemas).map(s => [s.$id, s]));
  function visit(value: any, document: any) {
    if (!value || typeof value !== 'object') return;
    if (value.$ref) {
      const [id, fragment] = value.$ref.split('#'); const root = id ? byId[id] : document;
      expect(root).toBeDefined(); expect(fragment ? fragment.slice(1).split('/').reduce((o: any, k: string) => o?.[k], root) : root).toBeDefined();
    }
    Object.values(value).forEach(child => visit(child, document));
  }
  for (const [name, schema] of Object.entries(schemas)) {
    const frozen = JSON.parse(fs.readFileSync(path.resolve(`src/data/monetaryContracts/schemas/${name.replaceAll('_', '-')}.schema.json`), 'utf8'));
    expect(schema).toEqual(frozen); visit(schema, schema);
  }
});
test('interpreter does not mutate shared runtime nodes on valid or invalid inputs', () => {
  const before = JSON.stringify(schemas);
  const freeze = (value: any) => { if (value && typeof value === 'object' && !Object.isFrozen(value)) { Object.freeze(value); Object.values(value).forEach(freeze); } };
  freeze(schemas); expect(() => assertMonetaryWire(savingsSubject(), 'subject')).not.toThrow();
  expect(() => assertMonetaryWire({ ...savingsSubject(), unexpected: true }, 'subject')).toThrow(); expect(JSON.stringify(schemas)).toBe(before);
});
test('all five frozen eligibility schemas and external/local references reconstruct unchanged', () => {
  const external: Record<string, any> = Object.fromEntries(Object.entries(eligibilitySchemas).map(([name, schema]) => [`executable-${name}-v2.schema.json`, schema]));
  function visit(value: any, root: any) {
    if (!value || typeof value !== 'object') return;
    if (value.$ref) expect(value.$ref.startsWith('#/') ? value.$ref.slice(2).split('/').reduce((o: any, key: string) => o?.[key], root) : external[value.$ref]).toBeDefined();
    Object.values(value).forEach(child => visit(child, root));
  }
  for (const [name, schema] of Object.entries(eligibilitySchemas)) {
    expect(schema).toEqual(JSON.parse(fs.readFileSync(path.resolve(`src/data/eligibilityContracts/executable-${name}-v2.schema.json`), 'utf8'))); visit(schema, schema);
  }
  const before = JSON.stringify(eligibilitySchemas);
  expect(() => assertEligibilityWire(eligibilitySubject(), 'subject')).not.toThrow();
  expect(() => assertEligibilityWire({ ...eligibilitySubject(), unexpected: true }, 'subject')).toThrow();
  expect(JSON.stringify(eligibilitySchemas)).toBe(before);
});
