import core from '../assets/sample/core.json';
import {
  lookupProvider,
  resolveBankLogoSources,
  resolveBrandShort,
} from '../src/data/bankBrand';
import type { CorePayload } from '../src/types';

const sample = core as CorePayload;

describe('bankBrand', () => {
  it('canonicalizes CDR provider labels like the dashboard', () => {
    expect(lookupProvider('CommBank')).toBe('commonwealth bank of australia');
    expect(lookupProvider('ING BANK (Australia) Ltd')).toBe('ing');
    expect(lookupProvider('NATIONAL AUSTRALIA BANK')).toBe('national australia bank');
    expect(lookupProvider('St.George Bank')).toBe('st. george bank');
  });

  it('resolves bundled logo sources for major lenders', () => {
    const providers = [
      'CommBank',
      'ING BANK (Australia) Ltd',
      'Westpac',
      'AMP - My AMP',
      'NATIONAL AUSTRALIA BANK',
    ];
    for (const provider of providers) {
      const sources = resolveBankLogoSources(provider);
      expect(sources.length).toBeGreaterThan(0);
      expect(
        sources.some(
          (src) =>
            typeof src === 'number' ||
            (typeof src === 'string' &&
              src.includes('raw.githubusercontent.com/yanniedog/AR-local/main/dashboard/assets/banks/')),
        ),
      ).toBe(true);
    }
  });

  it('prefers payload-embedded logos before bundled fallbacks', () => {
    const embedded = 'data:image/png;base64,abc';
    const sources = resolveBankLogoSources('ANZ', embedded);
    expect(sources[0]).toBe(embedded);
    expect(sources.length).toBeGreaterThan(1);
  });

  it('covers every logo-pack lender in the sample export', () => {
    const packProviders = [
      'AMP - My AMP',
      'AMP Bank GO',
      'ANZ',
      'Bank of Melbourne',
      'Bank of Queensland Limited',
      'Bankwest',
      'Bendigo Bank',
      'CommBank',
      'Great Southern Bank',
      'Great Southern Bank Business+',
      'HSBC',
      'HSBC Bank Australia Limited – Wholesale Banking',
      'ING BANK (Australia) Ltd',
      'Macquarie Bank Limited',
      'NATIONAL AUSTRALIA BANK',
      'St.George Bank',
      'Suncorp Bank',
      'Westpac',
    ];
    for (const provider of packProviders) {
      expect(resolveBankLogoSources(provider).length).toBeGreaterThan(0);
    }
    const sampleProviders = Object.keys(sample.brands ?? {});
    const withSources = sampleProviders.filter((p) => resolveBankLogoSources(p).length > 0);
    expect(withSources.length).toBeGreaterThanOrEqual(packProviders.length);
  });

  it('falls back to monogram short labels when no brand entry exists', () => {
    expect(resolveBrandShort('Some New Bank')).toBe('SNB');
  });

  it('uses the CDR Register logoUri for brands outside the pack', () => {
    const uri = 'https://mystate.com.au/wp-content/uploads/MyState_Logo_s.png';
    expect(resolveBankLogoSources('MyState Bank', undefined, uri)).toEqual([uri]);
    // Pack lenders keep bundled art first; the register URI rides last.
    const anz = resolveBankLogoSources('ANZ', undefined, uri);
    expect(anz[anz.length - 1]).toBe(uri);
    expect(anz.length).toBeGreaterThan(1);
    // No more guessed CDN URLs for unknown brands — monogram is the fallback.
    expect(resolveBankLogoSources('Totally Unknown Bank')).toEqual([]);
  });
});
