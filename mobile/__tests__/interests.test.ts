import { DEFAULT_PREFS, useStore } from '../src/data/store';
import {
  DEFAULT_INTERESTS,
  moveInterest,
  normalizeInterests,
  orderedInterestSections,
  resolveInterestSection,
  sectionSegmentOptions,
  toggleInterest,
} from '../src/data/interests';

describe('interests helpers', () => {
  it('normalizes unknown and duplicate keys', () => {
    expect(normalizeInterests(['Savings', 'Savings', 'TD' as never, 'Mortgage'])).toEqual([
      'Savings',
      'TD',
      'Mortgage',
    ]);
    expect(normalizeInterests([])).toEqual(DEFAULT_INTERESTS);
  });

  it('builds segment options in interest order', () => {
    expect(sectionSegmentOptions(['TD', 'Mortgage'])).toEqual([
      { value: 'TD', label: 'Deposits' },
      { value: 'Mortgage', label: 'Loans' },
    ]);
  });

  it('toggles and reorders interests', () => {
    expect(toggleInterest(['Mortgage', 'Savings'], 'TD')).toEqual(['Mortgage', 'Savings', 'TD']);
    expect(toggleInterest(['Mortgage'], 'Mortgage')).toEqual(['Mortgage']);
    expect(moveInterest(['Mortgage', 'Savings', 'TD'], 'TD', 'up')).toEqual([
      'Mortgage',
      'TD',
      'Savings',
    ]);
  });

  it('resolves preferred section when still selected', () => {
    expect(resolveInterestSection(['Savings', 'Mortgage'], 'Mortgage')).toBe('Mortgage');
    expect(resolveInterestSection(['Savings', 'Mortgage'], 'TD')).toBe('Savings');
  });

  it('orders sections for trends snapshot', () => {
    expect(orderedInterestSections(['TD', 'Mortgage'])).toEqual(['TD', 'Mortgage']);
  });
});

describe('store interests prefs', () => {
  beforeEach(() => {
    useStore.setState({ prefs: { ...DEFAULT_PREFS }, hydrated: true });
  });

  it('keeps defaultSection within interests when interests change', () => {
    useStore.getState().setPref('defaultSection', 'TD');
    useStore.getState().setPref('interests', ['Mortgage', 'Savings']);
    expect(useStore.getState().prefs.defaultSection).toBe('Mortgage');
    expect(useStore.getState().prefs.interests).toEqual(['Mortgage', 'Savings']);
  });

  it('rejects defaultSection outside interests', () => {
    useStore.getState().setPref('interests', ['Savings']);
    useStore.getState().setPref('defaultSection', 'Mortgage');
    expect(useStore.getState().prefs.defaultSection).toBe('Savings');
  });

  it('normalizes interests on onboarding complete', () => {
    useStore.getState().completeOnboarding(['TD', 'TD', 'Savings'], false);
    expect(useStore.getState().prefs.interests).toEqual(['TD', 'Savings']);
    expect(useStore.getState().prefs.defaultSection).toBe('TD');
  });
});
