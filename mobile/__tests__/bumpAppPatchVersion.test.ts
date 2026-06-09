const { bumpPatchVersion } = require('../scripts/bump-app-patch-version-pure.cjs');

describe('bumpPatchVersion', () => {
  it('increments patch segment', () => {
    expect(bumpPatchVersion('1.0.0')).toBe('1.0.1');
    expect(bumpPatchVersion('1.0.1')).toBe('1.0.2');
    expect(bumpPatchVersion('2.3.9')).toBe('2.3.10');
  });

  it('normalizes short semver', () => {
    expect(bumpPatchVersion('1.0')).toBe('1.0.1');
  });
});
