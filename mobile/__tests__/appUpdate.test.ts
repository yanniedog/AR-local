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

const changelogSummary = {
  schema_version: 1,
  repo: 'yanniedog/AR-local',
  versions: [
    {
      version: '1.0.0',
      date: null,
      summaryBullets: ['First'],
      releaseUrl: 'https://github.com/yanniedog/AR-local/releases/tag/app-v1.0.0',
    },
    {
      version: '1.0.1',
      date: null,
      summaryBullets: ['Second'],
      releaseUrl: 'https://github.com/yanniedog/AR-local/releases/tag/app-v1.0.1',
    },
    {
      version: '1.0.2',
      date: null,
      summaryBullets: ['Third'],
      releaseUrl: 'https://github.com/yanniedog/AR-local/releases/tag/app-v1.0.2',
    },
  ],
};

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
      expect(result.changelogs).toEqual([]);
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

  it('attaches cumulative changelogs when remote semver is newer', async () => {
    const remote: ApkManifest = {
      schema_version: 1,
      version: '1.0.2',
      build_number: '11',
      download_url: 'https://github.com/yanniedog/AR-local/releases/download/app-apk-latest/app-preview.apk',
    };
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: async () => remote })
      .mockResolvedValueOnce({ ok: true, json: async () => changelogSummary });

    const result = await checkForAppUpdateAt(manifestUrl, installed);
    expect(result.status).toBe('available');
    if (result.status === 'available') {
      expect(result.changelogs.map((c) => c.summaryBullets[0])).toEqual(['Second', 'Third']);
    }
  });

  it('omits changelogs on same-version build bump', async () => {
    const remote: ApkManifest = {
      schema_version: 1,
      version: '1.0.0',
      build_number: '43',
      download_url: 'https://github.com/yanniedog/AR-local/releases/download/app-apk-latest/app-preview.apk',
    };
    (global.fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => remote });

    const result = await checkForAppUpdateAt(manifestUrl, installed);
    expect(result.status).toBe('available');
    if (result.status === 'available') {
      expect(result.changelogs).toEqual([]);
    }
  });
});
