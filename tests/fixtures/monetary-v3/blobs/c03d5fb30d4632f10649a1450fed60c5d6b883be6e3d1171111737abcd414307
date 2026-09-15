import { Platform } from 'react-native';

import type { LogLevel } from './debugLog';
import {
  CRASHLYTICS_ERROR_CATEGORIES,
  CRASHLYTICS_PRIVACY_NOTICE_KEY,
  DIAGNOSTICS_PRIVACY_NOTICE_VERSION,
} from './privacyPolicy';

let crashReportsEnabled = false;

export type CrashlyticsLike = {
  log: (message: string) => void;
  recordError: (error: Error, name?: string) => void;
  setAttribute: (key: string, value: string) => Promise<void> | void;
  setCrashlyticsCollectionEnabled: (enabled: boolean) => Promise<void> | void;
  isCrashlyticsCollectionEnabled: boolean;
};

type ObservabilityDeps = {
  crashlytics: () => CrashlyticsLike;
};

let deps: ObservabilityDeps | null = null;

function loadNativeDeps(): ObservabilityDeps | null {
  if (Platform.OS === 'web') return null;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports -- lazy native bridge
    const crashlyticsModule = require('@react-native-firebase/crashlytics') as {
      getCrashlytics: () => { readonly isCrashlyticsCollectionEnabled: boolean };
      log: (instance: unknown, message: string) => void;
      recordError: (instance: unknown, error: Error, name?: string) => void;
      setAttribute: (instance: unknown, key: string, value: string) => Promise<unknown>;
      setCrashlyticsCollectionEnabled: (instance: unknown, enabled: boolean) => Promise<unknown>;
    };
    const instance = crashlyticsModule.getCrashlytics();
    const crashlytics: CrashlyticsLike = {
      get isCrashlyticsCollectionEnabled() {
        return instance.isCrashlyticsCollectionEnabled;
      },
      log: (message) => crashlyticsModule.log(instance, message),
      recordError: (error, name) => crashlyticsModule.recordError(instance, error, name),
      setAttribute: async (key, value) => {
        await crashlyticsModule.setAttribute(instance, key, value);
      },
      setCrashlyticsCollectionEnabled: async (enabled) => {
        await crashlyticsModule.setCrashlyticsCollectionEnabled(instance, enabled);
      },
    };
    return { crashlytics: () => crashlytics };
  } catch {
    return null;
  }
}

function getDeps(): ObservabilityDeps | null {
  if (deps) return deps;
  deps = loadNativeDeps();
  return deps;
}

/** Test hook — inject mocks or reset to lazy native load. */
export function setObservabilityDepsForTests(next: ObservabilityDeps | null): void {
  deps = next;
  if (!next) {
    crashReportsEnabled = false;
  }
}

export function isDiagnosticsEnabled(): boolean {
  return crashReportsEnabled;
}

/** @deprecated Compatibility wrapper for callers/tests predating split consent. */
export async function setDiagnosticsEnabled(enabled: boolean): Promise<void> {
  await setCrashReportsEnabled(enabled);
}

export async function setCrashReportsEnabled(enabled: boolean): Promise<void> {
  const native = getDeps();
  if (!native) {
    crashReportsEnabled = false;
    if (enabled) throw new Error('Crash reporting is unavailable on this device.');
    return;
  }
  const crashlytics = native.crashlytics();
  try {
    if (enabled) {
      // Persisted native consent can survive an app update. Disable collection
      // until the current notice marker is written so an older-consent event
      // can never be mistaken for a currently consented triage event.
      await crashlytics.setCrashlyticsCollectionEnabled(false);
      await crashlytics.setAttribute(
        CRASHLYTICS_PRIVACY_NOTICE_KEY,
        DIAGNOSTICS_PRIVACY_NOTICE_VERSION,
      );
    }
    await crashlytics.setCrashlyticsCollectionEnabled(enabled);
  } catch (error) {
    crashReportsEnabled = crashlytics.isCrashlyticsCollectionEnabled;
    throw error;
  }
  crashReportsEnabled = crashlytics.isCrashlyticsCollectionEnabled;
  if (crashReportsEnabled !== enabled) {
    throw new Error('Crash-reporting consent was not confirmed by the native service.');
  }
}

export function setSessionReplayEnabled(_enabled: boolean): Promise<void> {
  // Financial and diagnostic screens cannot be protected by a best-effort
  // asynchronous route pause. Keep replay fail-closed until independently
  // masked native capture is available.
  // The SDK is deliberately not initialized, so no asynchronous route
  // transition can expose a sensitive screen before capture pauses.
  return Promise.resolve();
}

/** Initialize the consent-gated Crashlytics collection state. */
export async function initObservability(): Promise<void> {
  await setCrashReportsEnabled(crashReportsEnabled);
}

/**
 * Forward only a fixed error category. Raw messages remain in the local debug
 * log: regex redaction cannot make arbitrary product, receipt, route or device
 * text safe for automatic telemetry.
 */
export function bridgeLogToCrashlytics(level: LogLevel, tag: string, _message: string): void {
  if (!crashReportsEnabled || level !== 'error') return;
  const native = getDeps();
  if (!native) return;

  const category = CRASHLYTICS_ERROR_CATEGORIES[tag] ?? 'component';
  const line = `[ERROR] category=${category}`;
  try {
    native.crashlytics().log(line);
    native.crashlytics().recordError(new Error(line), `AppError:${category}`);
  } catch {
    // non-fatal
  }
}
