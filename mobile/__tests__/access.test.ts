import { assessAccess } from '../src/data/access';
import type { ProductDetail } from '../src/types';

const elig = (codes: string[], extra: { name?: string; info?: string }[] = []): ProductDetail => ({
  eligibility: [
    ...codes.map((label) => ({ label })),
    ...extra.map((e) => ({ label: 'OTHER', ...e })),
  ],
});

describe('assessAccess', () => {
  it('treats a plain product with only universal codes as public', () => {
    const a = assessAccess('Basic Variable Home Loan', elig(['MIN_AGE', 'RESIDENCY_STATUS', 'NATURAL_PERSON']));
    expect(a.restricted).toBe(false);
    expect(a.verify).toBe(false);
    expect(a.badge).toBeNull();
  });

  it('flags STAFF-coded products as staff-restricted', () => {
    const a = assessAccess('Premium Package', elig(['STAFF', 'MIN_AGE']));
    expect(a.restricted).toBe(true);
    expect(a.categories).toContain('staff');
    expect(a.badge).toBe('Staff only');
  });

  it('flags the Coastline/People-First failure mode: name says staff, data does not', () => {
    // Real example: "People First and Her Staff Home Loan" with only universal codes.
    const a = assessAccess('People First and Her Staff Home Loan', elig(['MIN_AGE', 'NATURAL_PERSON', 'RESIDENCY_STATUS']));
    expect(a.restricted).toBe(true); // name signal
    expect(a.verify).toBe(true); // not structurally confirmed
    expect(a.summary).toMatch(/confirm|verify/i);
  });

  it('detects occupation restrictions from free-text additionalInfo', () => {
    const a = assessAccess('Salute Account', elig(['EMPLOYMENT_STATUS'], [{ info: 'Available to current and former Defence Force members' }]));
    expect(a.categories).toContain('occupation');
    expect(a.restricted).toBe(true);
  });

  it('detects business/SMSF products', () => {
    expect(assessAccess('SMSF Term Deposit', null).categories).toContain('business');
    expect(assessAccess('Business Term Deposit', elig(['BUSINESS'])).categories).toContain('business');
  });

  it('does not over-flag a public product whose name merely mentions a city', () => {
    const a = assessAccess('Bank of Melbourne Saver', elig(['MIN_AGE']));
    expect(a.restricted).toBe(false);
    expect(a.verify).toBe(false);
  });
});
