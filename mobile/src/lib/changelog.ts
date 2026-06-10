import { APK_RELEASE_TAG, REPO } from '../config';
import { versionGt } from './versionCompare';

export interface ChangelogManifestVersion {
  version: string;
  date?: string | null;
  summaryBullets: string[];
  releaseUrl: string;
}

export interface ChangelogSummaryManifest {
  schema_version: number;
  repo: string;
  generated_at?: string;
  versions: ChangelogManifestVersion[];
}

export interface VersionChangelogSummary {
  version: string;
  summaryBullets: string[];
  releaseUrl: string;
}

const SUMMARY_ASSET = 'changelog-summary.json';

export function changelogSummaryUrl(
  repo: string = REPO,
  tag: string = APK_RELEASE_TAG,
): string {
  return `https://github.com/${repo}/releases/download/${tag}/${SUMMARY_ASSET}`;
}

/** Derive rolling changelog-summary URL from the APK manifest URL. */
export function changelogSummaryUrlFromManifestUrl(manifestUrl: string): string {
  const withoutQuery = manifestUrl.split('?')[0] ?? manifestUrl;
  if (withoutQuery.endsWith('/app-apk-latest.json')) {
    return withoutQuery.replace(/\/app-apk-latest\.json$/i, `/${SUMMARY_ASSET}`);
  }
  return changelogSummaryUrl();
}

function cacheBust(url: string): string {
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}_=${Date.now()}`;
}

export function selectCumulativeChangelogs(
  manifest: ChangelogSummaryManifest,
  installedVersion: string,
  targetVersion: string,
): VersionChangelogSummary[] {
  return (manifest.versions ?? [])
    .filter(
      (row) => versionGt(row.version, installedVersion) && !versionGt(row.version, targetVersion),
    )
    .map((row) => ({
      version: row.version,
      summaryBullets: row.summaryBullets,
      releaseUrl: row.releaseUrl,
    }));
}

export async function fetchChangelogSummary(
  url: string = changelogSummaryUrl(),
): Promise<ChangelogSummaryManifest> {
  const res = await fetch(cacheBust(url));
  if (!res.ok) {
    throw new Error(`changelog summary HTTP ${res.status}`);
  }
  const data = (await res.json()) as ChangelogSummaryManifest;
  if (!Array.isArray(data.versions)) {
    throw new Error('changelog summary missing versions');
  }
  return data;
}

export async function fetchCumulativeChangelogs(
  manifestUrl: string,
  installedVersion: string,
  targetVersion: string,
): Promise<VersionChangelogSummary[]> {
  const summaryUrl = changelogSummaryUrlFromManifestUrl(manifestUrl);
  const manifest = await fetchChangelogSummary(summaryUrl);
  return selectCumulativeChangelogs(manifest, installedVersion, targetVersion);
}
