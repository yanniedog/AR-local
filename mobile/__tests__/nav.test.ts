import { parseBrowsePath } from '../src/lib/nav';

describe('parseBrowsePath', () => {
  test('splits dot-delimited path segments', () => {
    expect(parseBrowsePath('FIXED.OWNER')).toEqual(['FIXED', 'OWNER']);
  });

  test('returns empty array for missing path', () => {
    expect(parseBrowsePath()).toEqual([]);
    expect(parseBrowsePath('')).toEqual([]);
  });

  test('uses first element when expo-router returns string[]', () => {
    expect(parseBrowsePath(['FIXED.OWNER', 'OTHER'])).toEqual(['FIXED', 'OWNER']);
  });
});
