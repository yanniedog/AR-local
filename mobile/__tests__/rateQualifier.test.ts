import { conditionalNote, rateQualifier } from '../src/lib/rateQualifier';
import type { RateRow } from '../src/types';

function row(partial: Partial<RateRow>): RateRow {
  return {
    provider: 'Test Bank',
    product_key: 'k',
    product_name: 'P',
    rate: '0.05',
    ...partial,
  };
}

describe('rateQualifier', () => {
  it('treats a base savings rate as unconditional', () => {
    const q = rateQualifier(
      row({ ribbon_deposit_kind: 'base', taxonomy_path: 'SAVINGS.SAVINGS_ACCT.BASE.FLAT' }),
      'Savings',
    );
    expect(q.kind).toBe('base');
    expect(q.conditional).toBe(false);
    expect(q.shortLabel).toBe('');
  });

  it('flags a bonus savings rate as conditional', () => {
    const q = rateQualifier(row({ ribbon_deposit_kind: 'bonus' }), 'Savings');
    expect(q.kind).toBe('bonus');
    expect(q.conditional).toBe(true);
    expect(q.shortLabel).toBe('Bonus');
    expect(q.note).toMatch(/conditions/i);
  });

  it('flags an introductory savings rate with its reversion term', () => {
    const q = rateQualifier(row({ ribbon_deposit_kind: 'introductory', term: 'P6M' }), 'Savings');
    expect(q.kind).toBe('intro');
    expect(q.conditional).toBe(true);
    expect(q.introMonths).toBe(6);
    expect(q.shortLabel).toBe('Intro 6mo');
    expect(q.note).toMatch(/6 months/);
    // The reversion term must also survive in the label (used by the a11y string).
    expect(q.label).toMatch(/6 months/);
  });

  it('flags a bonus term deposit via ribbon_rate_structure', () => {
    const q = rateQualifier(row({ ribbon_rate_structure: 'bonus' }), 'TD');
    expect(q.kind).toBe('bonus');
    expect(q.conditional).toBe(true);
  });

  it('never flags mortgages (variable/fixed is rate type, not conditionality)', () => {
    const q = rateQualifier(row({ ribbon_rate_structure: 'variable' }), 'Mortgage');
    expect(q.kind).toBe('none');
    expect(q.conditional).toBe(false);
  });

  it('falls back to the taxonomy path for BONUS when the flat field is missing', () => {
    const q = rateQualifier(row({ taxonomy_path: 'SAVINGS.SAVINGS_ACCT.BONUS.TIERED' }), 'Savings');
    expect(q.kind).toBe('bonus');
    expect(q.conditional).toBe(true);
  });

  it('falls back to the taxonomy path for INTRO when the flat field is missing', () => {
    const q = rateQualifier(row({ taxonomy_path: 'SAVINGS.SAVINGS_ACCT.INTRO.FLAT' }), 'Savings');
    expect(q.kind).toBe('intro');
    expect(q.conditional).toBe(true);
  });

  it('matches the longer INTRODUCTORY taxonomy token too', () => {
    const q = rateQualifier(row({ taxonomy_path: 'SAVINGS.SAVINGS_ACCT.INTRODUCTORY.TIERED' }), 'Savings');
    expect(q.kind).toBe('intro');
    expect(q.conditional).toBe(true);
  });

  it('falls back to the taxonomy path for BASE (unconditional, no intro fields)', () => {
    const q = rateQualifier(row({ taxonomy_path: 'SAVINGS.SAVINGS_ACCT.BASE.FLAT' }), 'Savings');
    expect(q.kind).toBe('base');
    expect(q.conditional).toBe(false);
    expect(q.introMonths).toBeNull();
    expect(q.shortLabel).toBe('');
  });

  it('conditionalNote returns text only for conditional rates, across sections', () => {
    // Savings
    expect(conditionalNote(row({ ribbon_deposit_kind: 'base' }), 'Savings')).toBe('');
    expect(conditionalNote(row({ ribbon_deposit_kind: 'bonus' }), 'Savings')).toMatch(/Bonus/);
    // Bonus wording is generic — it must not assert monthly conditions for
    // savings or TD, since neither is provable from the flat row.
    const savNote = conditionalNote(row({ ribbon_deposit_kind: 'bonus' }), 'Savings');
    expect(savNote).toMatch(/Bonus/);
    expect(savNote).not.toMatch(/monthly/i);
    const tdNote = conditionalNote(row({ ribbon_rate_structure: 'bonus' }), 'TD');
    expect(tdNote).toMatch(/Bonus/);
    expect(tdNote).not.toMatch(/monthly/i);
    // Mortgages never flag, even with a conditional-looking structure
    expect(conditionalNote(row({ ribbon_rate_structure: 'bonus' }), 'Mortgage')).toBe('');
    expect(conditionalNote(null, 'Savings')).toBe('');
  });
});
