import { M3_NAV_BAR_HEIGHT } from '../src/lib/androidChrome';
import {
  getTabIonicon,
  getTabLabel,
  getTabMaterialSymbol,
  TAB_MATERIAL_SYMBOLS,
  TAB_ROUTES,
} from '../src/lib/tabIcons';

describe('tabIcons', () => {
  it('maps every tab route to a material symbol and ionicon', () => {
    for (const route of TAB_ROUTES) {
      expect(getTabMaterialSymbol(route)).toBe(TAB_MATERIAL_SYMBOLS[route]);
      expect(getTabIonicon(route)).toBeTruthy();
      expect(getTabLabel(route)).toBeTruthy();
    }
  });

  it('returns undefined for unknown routes', () => {
    expect(getTabMaterialSymbol('unknown')).toBeUndefined();
    expect(getTabIonicon('unknown')).toBeUndefined();
    expect(getTabLabel('unknown', 'Fallback')).toBe('Fallback');
  });
});

describe('androidChrome', () => {
  it('exports M3 navigation bar height', () => {
    expect(M3_NAV_BAR_HEIGHT).toBe(80);
  });
});
