import { lvrTierForValue, parseLvrTier } from '../src/data/profile';

// Real data values from core.sections.Mortgage.rates[].lvr_tier
const TIERS = [
  'lvr_=60%',
  'lvr_60-70%',
  'lvr_70-80%',
  'lvr_80-85%',
  'lvr_85-90%',
  'lvr_90-95%',
  'lvr_unspecified',
];

describe('parseLvrTier', () => {
  it('parses the data tier formats into (lo, hi] ranges', () => {
    expect(parseLvrTier('lvr_=60%')).toEqual({ lo: 0, hi: 60 });
    expect(parseLvrTier('lvr_85-90%')).toEqual({ lo: 85, hi: 90 });
    expect(parseLvrTier('lvr_unspecified')).toBeNull();
    expect(parseLvrTier('')).toBeNull();
  });
});

describe('lvrTierForValue', () => {
  it('maps a computed LVR to the band that contains it', () => {
    expect(lvrTierForValue(55, TIERS)).toBe('lvr_=60%');
    expect(lvrTierForValue(60, TIERS)).toBe('lvr_=60%'); // upper-inclusive
    expect(lvrTierForValue(72.5, TIERS)).toBe('lvr_70-80%');
    expect(lvrTierForValue(88, TIERS)).toBe('lvr_85-90%');
    expect(lvrTierForValue(93, TIERS)).toBe('lvr_90-95%');
  });

  it('clamps an LVR above every band to the highest band', () => {
    expect(lvrTierForValue(98, TIERS)).toBe('lvr_90-95%');
  });

  it('returns null for non-positive / non-finite LVR or when no usable tiers exist', () => {
    expect(lvrTierForValue(0, TIERS)).toBeNull();
    expect(lvrTierForValue(NaN, TIERS)).toBeNull();
    expect(lvrTierForValue(80, ['lvr_unspecified'])).toBeNull();
  });
});
