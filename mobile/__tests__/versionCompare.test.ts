import {
  buildNumberLt,
  isUpdateAvailable,
  versionLt,
} from '../src/lib/versionCompare';

describe('versionCompare', () => {
  describe('versionLt', () => {
    it('compares semver segments', () => {
      expect(versionLt('1.0.0', '1.0.1')).toBe(true);
      expect(versionLt('1.0.1', '1.0.0')).toBe(false);
      expect(versionLt('1.0.0', '1.0.0')).toBe(false);
      expect(versionLt('1.9.9', '2.0.0')).toBe(true);
    });

    it('handles missing patch segments', () => {
      expect(versionLt('1.0', '1.0.1')).toBe(true);
      expect(versionLt('1', '1.0.1')).toBe(true);
    });
  });

  describe('buildNumberLt', () => {
    it('compares numeric build codes', () => {
      expect(buildNumberLt('41', '42')).toBe(true);
      expect(buildNumberLt('42', '42')).toBe(false);
      expect(buildNumberLt('100', '99')).toBe(false);
    });
  });

  describe('isUpdateAvailable', () => {
    it('prefers version over build number', () => {
      expect(isUpdateAvailable('1.0.0', '99', '1.0.1', '1')).toBe(true);
      expect(isUpdateAvailable('1.0.1', '1', '1.0.0', '99')).toBe(false);
    });

    it('uses build number when versions match', () => {
      expect(isUpdateAvailable('1.0.0', '41', '1.0.0', '42')).toBe(true);
      expect(isUpdateAvailable('1.0.0', '42', '1.0.0', '42')).toBe(false);
      expect(isUpdateAvailable('1.0.0', '43', '1.0.0', '42')).toBe(false);
    });
  });
});
