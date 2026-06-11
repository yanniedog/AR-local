import {
  DEPOSIT_SECTIONS,
  LOAN_SECTIONS,
  isLoanSection,
  moveTone,
  moveVerb,
} from '../src/lib/moveSemantics';

describe('moveSemantics', () => {
  it('classifies sections by customer perspective', () => {
    expect(isLoanSection('Mortgage')).toBe(true);
    expect(isLoanSection('Savings')).toBe(false);
    expect(isLoanSection('TD')).toBe(false);
    expect(LOAN_SECTIONS).toContain('Mortgage');
    expect(DEPOSIT_SECTIONS).toEqual(expect.arrayContaining(['Savings', 'TD']));
  });

  describe('moveTone', () => {
    it('colours mortgage hikes red and cuts green', () => {
      expect(moveTone('Mortgage', 25)).toBe('danger');
      expect(moveTone('Mortgage', -25)).toBe('success');
    });

    it('colours savings/TD increases green and decreases red', () => {
      expect(moveTone('Savings', 25)).toBe('success');
      expect(moveTone('Savings', -25)).toBe('danger');
      expect(moveTone('TD', 10)).toBe('success');
      expect(moveTone('TD', -10)).toBe('danger');
    });

    it('mutes zero moves', () => {
      expect(moveTone('Mortgage', 0)).toBe('muted');
      expect(moveTone('Savings', 0)).toBe('muted');
    });
  });

  describe('moveVerb', () => {
    it('keeps hike/cut for loans only', () => {
      expect(moveVerb('Mortgage', 'cut')).toBe('cut');
      expect(moveVerb('Mortgage', 'hike')).toBe('hiked');
    });

    it('uses increase/decrease for savings and term deposits', () => {
      expect(moveVerb('Savings', 'hike')).toBe('increased');
      expect(moveVerb('Savings', 'cut')).toBe('decreased');
      expect(moveVerb('TD', 'hike')).toBe('increased');
      expect(moveVerb('TD', 'cut')).toBe('decreased');
    });

    it('falls back to repriced for mixed moves', () => {
      expect(moveVerb('Mortgage', 'mixed')).toBe('repriced');
      expect(moveVerb('Savings', 'mixed')).toBe('repriced');
    });
  });
});
