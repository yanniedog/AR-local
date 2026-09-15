import { Platform } from 'react-native';
import type { CrashlyticsLike, ObservabilityDeps } from './observability';

export function loadNativeDeps(): ObservabilityDeps | null {
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

