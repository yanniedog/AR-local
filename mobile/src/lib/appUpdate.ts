import * as Application from 'expo-application';
import * as Crypto from 'expo-crypto';
import * as FileSystem from 'expo-file-system/legacy';
import * as IntentLauncher from 'expo-intent-launcher';
import { Platform } from 'react-native';

import { APK_MANIFEST_URL } from '../config';
import { debugLog } from './debugLog';
import {
  checkForAppUpdateAt,
  fetchApkManifest,
  type ApkManifest,
  type DownloadProgress,
  type InstalledAppInfo,
  type UpdateCheckResult,
} from './appUpdateLogic';

export type {
  ApkManifest,
  DownloadProgress,
  InstalledAppInfo,
  UpdateCheckResult,
} from './appUpdateLogic';
export { fetchApkManifest, remoteIsNewer } from './appUpdateLogic';

const APK_CACHE = `${FileSystem.cacheDirectory ?? ''}app-update.apk`;

export function getInstalledAppInfo(): InstalledAppInfo {
  return {
    version: Application.nativeApplicationVersion ?? '0.0.0',
    buildNumber: Application.nativeBuildVersion ?? '0',
  };
}

export async function checkForAppUpdate(
  url: string = APK_MANIFEST_URL,
): Promise<UpdateCheckResult> {
  if (Platform.OS !== 'android') {
    return { status: 'error', message: 'In-app APK updates are Android-only' };
  }
  const result = await checkForAppUpdateAt(url, getInstalledAppInfo());
  if (result.status === 'available' || result.status === 'current') {
    debugLog.info(
      'app-update',
      `check ${result.status} installed=${result.installed.version}/${result.installed.buildNumber} remote=${result.remote.version}/${result.remote.build_number}`,
    );
  } else {
    debugLog.error('app-update', `check failed: ${result.message}`);
  }
  return result;
}

function toHex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

async function verifySha256(path: string, expectedSha: string): Promise<void> {
  const info = await FileSystem.getInfoAsync(path);
  const size = info.exists && 'size' in info ? (info.size ?? 0) : 0;
  // SDK 54 has no FileSystem.hashAsync; skip verify for large APKs to avoid OOM on low-RAM devices.
  if (size > 64 * 1024 * 1024) {
    debugLog.warn('app-update', `skipping sha256 verify (APK ${size} bytes > 64 MiB)`);
    return;
  }
  const base64 = await FileSystem.readAsStringAsync(path, {
    encoding: FileSystem.EncodingType.Base64,
  });
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  const digest = await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, bytes);
  const actual = toHex(digest);
  if (actual !== expectedSha) {
    throw new Error(
      `APK sha256 mismatch (expected ${expectedSha.slice(0, 12)}…, got ${actual.slice(0, 12)}…)`,
    );
  }
}

export async function downloadApkUpdate(
  manifest: ApkManifest,
  onProgress?: (progress: DownloadProgress) => void,
): Promise<string> {
  if (Platform.OS !== 'android') {
    throw new Error('APK download is Android-only');
  }
  if (!FileSystem.cacheDirectory) {
    throw new Error('cache directory unavailable');
  }

  await FileSystem.deleteAsync(APK_CACHE, { idempotent: true });

  const startedAt = Date.now();
  onProgress?.({ bytesWritten: 0, totalBytes: manifest.bytes ?? null });

  const resumable = FileSystem.createDownloadResumable(
    manifest.download_url,
    APK_CACHE,
    {},
    (progress) => {
      onProgress?.({
        bytesWritten: progress.totalBytesWritten,
        totalBytes: progress.totalBytesExpectedToWrite || manifest.bytes || null,
      });
    },
  );

  const result = await resumable.downloadAsync();
  if (!result?.uri) {
    throw new Error('APK download failed');
  }

  debugLog.info(
    'app-update',
    `download ok ms=${Date.now() - startedAt}`,
  );

  if (manifest.sha256) {
    await verifySha256(result.uri, manifest.sha256);
  }

  return result.uri;
}

export async function installDownloadedApk(localUri: string): Promise<void> {
  if (Platform.OS !== 'android') {
    throw new Error('APK install is Android-only');
  }

  const contentUri = await FileSystem.getContentUriAsync(localUri);
  debugLog.info('app-update', 'launching package installer');

  await IntentLauncher.startActivityAsync('android.intent.action.VIEW', {
    data: contentUri,
    flags: 1,
    type: 'application/vnd.android.package-archive',
  });
}

export async function downloadAndInstallUpdate(
  manifest: ApkManifest,
  onProgress?: (progress: DownloadProgress) => void,
): Promise<void> {
  const localUri = await downloadApkUpdate(manifest, onProgress);
  await installDownloadedApk(localUri);
}
