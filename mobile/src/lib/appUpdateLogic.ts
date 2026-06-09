import { isUpdateAvailable } from './versionCompare';

export interface ApkManifest {
  schema_version: number;
  version: string;
  build_number: string;
  download_url: string;
  sha256?: string;
  bytes?: number;
  published_at?: string;
  repo?: string;
  tag?: string;
  eas_build_id?: string;
  profile?: string;
}

export interface InstalledAppInfo {
  version: string;
  buildNumber: string;
}

export type UpdateCheckResult =
  | { status: 'current'; installed: InstalledAppInfo; remote: ApkManifest }
  | { status: 'available'; installed: InstalledAppInfo; remote: ApkManifest }
  | { status: 'error'; message: string };

export type DownloadProgress = {
  bytesWritten: number;
  totalBytes: number | null;
};

function manifestFetchUrl(url: string): string {
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}_=${Date.now()}`;
}

export function remoteIsNewer(installed: InstalledAppInfo, remote: ApkManifest): boolean {
  return isUpdateAvailable(
    installed.version,
    installed.buildNumber,
    remote.version,
    remote.build_number,
  );
}

export async function fetchApkManifest(url: string): Promise<ApkManifest> {
  const res = await fetch(manifestFetchUrl(url));
  if (!res.ok) {
    throw new Error(`APK manifest HTTP ${res.status}`);
  }
  const m = (await res.json()) as ApkManifest;
  if (typeof m.version !== 'string' || typeof m.build_number !== 'string') {
    throw new Error('APK manifest missing version or build_number');
  }
  if (typeof m.download_url !== 'string' || !m.download_url.startsWith('https://')) {
    throw new Error('APK manifest missing download_url');
  }
  return m;
}

export async function checkForAppUpdateAt(
  manifestUrl: string,
  installed: InstalledAppInfo,
): Promise<UpdateCheckResult> {
  try {
    const remote = await fetchApkManifest(manifestUrl);
    if (remoteIsNewer(installed, remote)) {
      return { status: 'available', installed, remote };
    }
    return { status: 'current', installed, remote };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { status: 'error', message };
  }
}
