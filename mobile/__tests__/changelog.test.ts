import {
  changelogSummaryUrl,
  changelogSummaryUrlFromManifestUrl,
  selectCumulativeChangelogs,
  type ChangelogManifestVersion,
} from '../src/lib/changelog';

const versions: ChangelogManifestVersion[] = [
  {
    version: '1.0.0',
    date: '2026-06-01',
    summaryBullets: ['First'],
    releaseUrl: 'https://github.com/yanniedog/AR-local/releases/tag/app-v1.0.0',
  },
  {
    version: '1.0.1',
    date: '2026-06-05',
    summaryBullets: ['Second'],
    releaseUrl: 'https://github.com/yanniedog/AR-local/releases/tag/app-v1.0.1',
  },
  {
    version: '1.0.2',
    date: '2026-06-09',
    summaryBullets: ['Third'],
    releaseUrl: 'https://github.com/yanniedog/AR-local/releases/tag/app-v1.0.2',
  },
];

describe('changelog', () => {
  it('changelogSummaryUrl points at rolling release asset', () => {
    expect(changelogSummaryUrl('yanniedog/AR-local', 'app-apk-latest')).toBe(
      'https://github.com/yanniedog/AR-local/releases/download/app-apk-latest/changelog-summary.json',
    );
  });

  it('changelogSummaryUrlFromManifestUrl derives summary URL from manifest URL', () => {
    expect(
      changelogSummaryUrlFromManifestUrl(
        'https://github.com/yanniedog/AR-local/releases/download/app-apk-latest/app-apk-latest.json',
      ),
    ).toBe(
      'https://github.com/yanniedog/AR-local/releases/download/app-apk-latest/changelog-summary.json',
    );
    expect(
      changelogSummaryUrlFromManifestUrl(
        'https://github.com/yanniedog/AR-local/releases/download/app-apk-latest/app-apk-latest.json?cache=1',
      ),
    ).toBe(
      'https://github.com/yanniedog/AR-local/releases/download/app-apk-latest/changelog-summary.json',
    );
  });

  it('changelogSummaryUrlFromManifestUrl falls back for non-rolling manifests', () => {
    expect(
      changelogSummaryUrlFromManifestUrl('https://example.com/releases/app-v1.0.0.json'),
    ).toBe(changelogSummaryUrl());
  });

  it('selectCumulativeChangelogs returns skipped versions only', () => {
    const manifest = { schema_version: 1, repo: 'yanniedog/AR-local', versions };
    const picked = selectCumulativeChangelogs(manifest, '1.0.0', '1.0.2');
    expect(picked.map((v) => v.version)).toEqual(['1.0.1', '1.0.2']);
    expect(picked[0].summaryBullets).toEqual(['Second']);
    expect(picked[1].summaryBullets).toEqual(['Third']);
  });

  it('selectCumulativeChangelogs is empty when already on target', () => {
    const manifest = { schema_version: 1, repo: 'yanniedog/AR-local', versions };
    expect(selectCumulativeChangelogs(manifest, '1.0.2', '1.0.2')).toEqual([]);
  });
});
