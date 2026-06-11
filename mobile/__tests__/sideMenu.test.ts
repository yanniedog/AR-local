import { MENU_SECTIONS } from '../src/components/SideMenu';

describe('SideMenu destinations', () => {
  const items = MENU_SECTIONS.flatMap((s) => s.items);

  it('covers every tab plus the secondary screens', () => {
    const routes = items.map((i) => String(i.route));
    for (const required of ['/', '/browse', '/watchlist', '/trends', '/settings', '/banks', '/search', '/compare', '/terms', '/debug-log']) {
      expect(routes).toContain(required);
    }
  });

  it('has no duplicate routes or labels', () => {
    const routes = items.map((i) => String(i.route));
    const labels = items.map((i) => i.label);
    expect(new Set(routes).size).toBe(routes.length);
    expect(new Set(labels).size).toBe(labels.length);
  });
});
