import {
  extractChangelogSection,
  releaseTitle,
  versionTag,
} from '../scripts/app-release-meta.mjs';

describe('app-release-meta', () => {
  it('versionTag uses app-v prefix', () => {
    expect(versionTag('1.0.0')).toBe('app-v1.0.0');
    expect(versionTag('2.3.4')).toBe('app-v2.3.4');
  });

  it('releaseTitle matches documented format', () => {
    expect(releaseTitle('1.0.0')).toBe('Australian Rates app — 1.0.0 (Android)');
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
