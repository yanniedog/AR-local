import { conditionalNote, ongoingRateCaveat, rateQualifier } from '../src/lib/rateQualifier';
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

  it('names the published ongoing rate a bonus reverts to', () => {
    const q = rateQualifier(row({ ribbon_deposit_kind: 'bonus', rate: '0.05', ongoing_rate: '0.01' }), 'Savings');
    expect(q.ongoingRate).toBe('1.00%');
    expect(q.note).toMatch(/ongoing rate is 1\.00%/);
  });

  it('names the reversion target and term for an intro rate', () => {
    const q = rateQualifier(
      row({ ribbon_deposit_kind: 'introductory', term: 'P4M', rate: '0.05', ongoing_rate: '0.015' }),
      'Savings',
    );
    expect(q.ongoingRate).toBe('1.50%');
    expect(q.note).toMatch(/applies for 4 months, then reverts to 1\.50%/);
    // The a11y label must carry both the term and the reversion target.
    expect(q.label).toMatch(/4 months, then 1\.50%/);
  });

  it('says the ongoing rate is unpublished when no base tier exists', () => {
    const q = rateQualifier(row({ ribbon_deposit_kind: 'bonus', rate: '0.05' }), 'Savings');
    expect(q.ongoingRate).toBeNull();
    expect(q.note).toMatch(/does not publish a separate base rate/);
  });

  it('ongoingRateCaveat is a compact reversion sentence (or empty)', () => {
    expect(ongoingRateCaveat(row({ ribbon_deposit_kind: 'base' }), 'Savings')).toBe('');
    expect(ongoingRateCaveat(row({ ribbon_deposit_kind: 'bonus', ongoing_rate: '0.01' }), 'Savings')).toBe(
      "Ongoing rate 1.00% when bonus conditions aren't met.",
    );
    expect(
      ongoingRateCaveat(row({ ribbon_deposit_kind: 'introductory', term: 'P6M', ongoing_rate: '0.02' }), 'Savings'),
    ).toBe('Reverts to 2.00% after 6 months.');
    // Intro with a known target but no term.
    expect(ongoingRateCaveat(row({ ribbon_deposit_kind: 'introductory', ongoing_rate: '0.02' }), 'Savings')).toBe(
      'Reverts to 2.00% after the intro period.',
    );
    // Intro with no published ongoing rate.
    expect(ongoingRateCaveat(row({ ribbon_deposit_kind: 'introductory', term: 'P3M' }), 'Savings')).toBe(
      'Reverts to a lower ongoing rate after 3 months (not published).',
    );
  });

  it('treats a published 0% ongoing rate as published, not missing', () => {
    const q = rateQualifier(row({ ribbon_deposit_kind: 'bonus', rate: '0.05', ongoing_rate: '0' }), 'Savings');
    expect(q.ongoingRate).toBe('0.00%');
    expect(q.note).toMatch(/ongoing rate is 0\.00%/);
    expect(q.note).not.toMatch(/not publish/);
  });
});
