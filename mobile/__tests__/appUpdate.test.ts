import {
  checkForAppUpdateAt,
  fetchApkManifest,
  remoteIsNewer,
  type ApkManifest,
} from '../src/lib/appUpdateLogic';

const baseManifest: ApkManifest = {
  schema_version: 1,
  version: '1.0.0',
  build_number: '42',
  download_url: 'https://github.com/yanniedog/AR-local/releases/download/app-apk-latest/app-preview.apk',
  published_at: '2026-06-09T00:00:00Z',
};

const installed = { version: '1.0.0', buildNumber: '41' };
const manifestUrl =
  'https://github.com/yanniedog/AR-local/releases/download/app-apk-latest/app-apk-latest.json';

describe('appUpdateLogic', () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  it('detects newer remote build on same version', () => {
    expect(remoteIsNewer(installed, baseManifest)).toBe(true);
  });

  it('parses a valid APK manifest', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => baseManifest,
    });
    await expect(fetchApkManifest(manifestUrl)).resolves.toEqual(baseManifest);
  });

  it('reports available update when remote build is newer', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => baseManifest,
    });
    const result = await checkForAppUpdateAt(manifestUrl, installed);
    expect(result.status).toBe('available');
    if (result.status === 'available') {
      expect(result.remote.build_number).toBe('42');
    }
  });

  it('reports current when installed matches remote', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ ...baseManifest, build_number: '41' }),
    });
    const result = await checkForAppUpdateAt(manifestUrl, installed);
    expect(result.status).toBe('current');
  });

  it('surfaces manifest HTTP errors', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: false, status: 404 });
    const result = await checkForAppUpdateAt(manifestUrl, installed);
    expect(result.status).toBe('error');
    if (result.status === 'error') {
      expect(result.message).toContain('404');
    }
  });
});
