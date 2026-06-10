import * as Application from 'expo-application';
import * as Device from 'expo-device';
import * as IntentLauncher from 'expo-intent-launcher';
import { Alert, Linking, Platform } from 'react-native';

import { ANDROID_PACKAGE, debugLog } from './debugLog';

/**
 * Install-unknown-apps permission is prompted from Settings → App update, not
 * first-run onboarding. Onboarding defers sideload UX so users see rate value first.
 */

/** Android O (API 26)+ requires per-app "Install unknown apps" before sideloading. */
export const INSTALL_PERMISSION_MIN_API = 26;

export type InstallPermissionState =
  | 'granted'
  | 'required'
  | 'not_applicable';

export function resolveInstallPermissionState(
  platformOs: string,
  apiLevel: number | null | undefined,
  canInstall: boolean,
): InstallPermissionState {
  if (platformOs !== 'android') return 'not_applicable';
  if (apiLevel != null && apiLevel < INSTALL_PERMISSION_MIN_API) return 'granted';
  return canInstall ? 'granted' : 'required';
}

export function installPermissionPackageUri(
  applicationId: string | null | undefined = Application.applicationId,
): string {
  const pkg = applicationId?.trim() || ANDROID_PACKAGE;
  return `package:${pkg}`;
}

export async function canInstallApkUpdates(): Promise<boolean> {
  if (Platform.OS !== 'android') return false;
  const apiLevel = Device.platformApiLevel;
  if (apiLevel != null && apiLevel < INSTALL_PERMISSION_MIN_API) return true;
  try {
    return await Device.isSideLoadingEnabledAsync();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    debugLog.warn('install-permission', `check failed: ${message}`);
    return false;
  }
}

export async function getInstallPermissionState(): Promise<InstallPermissionState> {
  const canInstall = await canInstallApkUpdates();
  return resolveInstallPermissionState(
    Platform.OS,
    Device.platformApiLevel,
    canInstall,
  );
}

export async function openInstallPermissionSettings(): Promise<void> {
  if (Platform.OS !== 'android') return;

  const data = installPermissionPackageUri();
  try {
    await IntentLauncher.startActivityAsync(
      'android.settings.MANAGE_UNKNOWN_APP_SOURCES',
      { data },
    );
    return;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    debugLog.warn('install-permission', `settings intent failed: ${message}`);
  }

  await Linking.openSettings();
}

export function promptInstallPermissionSettings(
  onOpenSettings?: () => void,
): void {
  Alert.alert(
    'Allow app updates',
    'Required to install updates from the app.',
    [
      { text: 'Not now', style: 'cancel' },
      {
        text: 'Open settings',
        onPress: () => {
          onOpenSettings?.();
          void openInstallPermissionSettings();
        },
      },
    ],
  );
}

/**
 * Returns true when sideload install is allowed. When false, shows a one-shot prompt
 * and opens system settings (Android 8+ only). Not used during onboarding — Settings
 * App update section and the download flow call this before install.
 */
export async function ensureInstallPermission(options?: {
  prompt?: boolean;
}): Promise<boolean> {
  const state = await getInstallPermissionState();
  if (state !== 'required') return state === 'granted';

  if (options?.prompt !== false) {
    promptInstallPermissionSettings();
  }
  return false;
}
