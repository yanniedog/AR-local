import { Platform } from 'react-native';

import type { LogLevel } from './debugLog';

let diagnosticsEnabled = true;
let clarityInitialized = false;

export type CrashlyticsLike = {
  log: (message: string) => void;
  recordError: (error: Error, name?: string) => void;
  setCrashlyticsCollectionEnabled: (enabled: boolean) => Promise<void> | void;
};

export type ClarityLike = {
  initialize: (projectId: string) => void;
  pause: () => Promise<boolean>;
  resume: () => Promise<boolean>;
};

type ObservabilityDeps = {
  crashlytics: () => CrashlyticsLike;
  clarity: ClarityLike;
};

let deps: ObservabilityDeps | null = null;

function loadNativeDeps(): ObservabilityDeps | null {
  if (Platform.OS === 'web') return null;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports -- lazy native bridge
    const crashlytics = require('@react-native-firebase/crashlytics').default as () => CrashlyticsLike;
    // eslint-disable-next-line @typescript-eslint/no-require-imports -- lazy native bridge
    const clarity = require('@microsoft/react-native-clarity') as ClarityLike;
    return { crashlytics, clarity };
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
}

export function isDiagnosticsEnabled(): boolean {
  return diagnosticsEnabled;
}

export async function setDiagnosticsEnabled(enabled: boolean): Promise<void> {
  diagnosticsEnabled = enabled;
  const native = getDeps();
  if (!native) return;
  try {
    await native.crashlytics().setCrashlyticsCollectionEnabled(enabled);
    if (clarityInitialized) {
      if (enabled) await native.clarity.resume();
      else await native.clarity.pause();
    }
  } catch {
    // Expo Go / tests without native modules
  }
}

/** Initialize Clarity (preview/production) and Crashlytics collection. */
export async function initObservability(): Promise<void> {
  const native = getDeps();
  if (!native) return;

  try {
    await native.crashlytics().setCrashlyticsCollectionEnabled(diagnosticsEnabled);
  } catch {
    // non-fatal
  }

  const projectId = process.env.EXPO_PUBLIC_CLARITY_PROJECT_ID?.trim();
  if (!projectId || __DEV__ || !diagnosticsEnabled) return;

  try {
    native.clarity.initialize(projectId);
    clarityInitialized = true;
  } catch {
    // native module unavailable
  }
}

/** Forward debugLog lines to Crashlytics when diagnostics are enabled. */
export function bridgeLogToCrashlytics(level: LogLevel, tag: string, message: string): void {
  if (!diagnosticsEnabled || level === 'debug') return;
  const native = getDeps();
  if (!native) return;

  const line = `[${level.toUpperCase()}] ${tag}: ${message}`;
  try {
    native.crashlytics().log(line);
    if (level === 'error') {
      native.crashlytics().recordError(new Error(line), tag);
    }
  } catch {
    // non-fatal
  }
}
