const {
  versionTag,
  releaseTitle,
  extractChangelogSection,
} = require('../scripts/app-release-meta-pure.cjs');

const {
  CHANGELOG_SUMMARY_ASSET,
  renderGithubReleaseBody,
  selectCumulativeSummaries,
  versionGt,
} = require('../scripts/changelog-lib.cjs');

describe('app-release-meta', () => {
  it('versionTag uses app-v prefix', () => {
    expect(versionTag('1.0.0')).toBe('app-v1.0.0');
    expect(versionTag('2.3.4')).toBe('app-v2.3.4');
  });

  it('releaseTitle matches documented format', () => {
    expect(releaseTitle('1.0.0')).toBe('Australian Rates app \u2013 1.0.0 (Android)');
  });

  it('extractChangelogSection reads version block from CHANGELOG.md', () => {
    const md = `# Changelog

## 1.0.0

- First release
- QR install

## 0.9.0

- Beta
`;
    const section = extractChangelogSection(md, '1.0.0');
    expect(section).toContain('## 1.0.0');
    expect(section).toContain('First release');
    expect(section).not.toContain('0.9.0');
  });
});

describe('changelog-lib', () => {
  it('CHANGELOG_SUMMARY_ASSET is changelog-summary.json', () => {
    expect(CHANGELOG_SUMMARY_ASSET).toBe('changelog-summary.json');
  });

  it('versionGt orders semver', () => {
    expect(versionGt('1.0.2', '1.0.1')).toBe(true);
    expect(versionGt('1.0.1', '1.0.2')).toBe(false);
  });

  it('selectCumulativeSummaries picks First/Second/Third test data', () => {
    const manifest = {
      versions: [
        { version: '1.0.0', summaryBullets: ['First'], releaseUrl: 'u0' },
        { version: '1.0.1', summaryBullets: ['Second'], releaseUrl: 'u1' },
        { version: '1.0.2', summaryBullets: ['Third'], releaseUrl: 'u2' },
      ],
    };
    const picked = selectCumulativeSummaries(manifest, '1.0.0', '1.0.2');
    expect(picked.map((v: { summaryBullets: string[] }) => v.summaryBullets[0])).toEqual(['Second', 'Third']);
  });

  it('renderGithubReleaseBody wraps sections in details and includes install + changelog info', () => {
    const body = renderGithubReleaseBody({
      entry: {
        version: '1.0.0',
        date: '2026-06-01',
        summaryBullets: ['First'],
        sections: [{ title: 'Initial', bullets: [{ text: 'Line one' }] }],
      },
      buildNumber: '42',
      repo: 'yanniedog/AR-local',
    });
    expect(body).toContain('<details>');
    expect(body).toContain('Line one');
    expect(body).toContain('Build 42');
    expect(body).toContain('<summary>Install</summary>');
    expect(body).toContain('changelog-summary.json');
    expect(body).toContain('Rolling manifest');
  });
});
