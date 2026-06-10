// Mock native-only Expo modules so unit tests (pure logic) can import data modules
// without a native runtime. The app uses the real modules on device.
jest.mock('expo-haptics', () => ({
  selectionAsync: jest.fn(async () => {}),
  impactAsync: jest.fn(async () => {}),
  notificationAsync: jest.fn(async () => {}),
  ImpactFeedbackStyle: { Light: 'light' },
  NotificationFeedbackType: { Success: 'success' },
}));

jest.mock('expo-task-manager', () => ({
  defineTask: jest.fn(),
  isTaskDefined: jest.fn(() => false),
  unregisterTaskAsync: jest.fn(async () => {}),
}));

jest.mock('expo-background-fetch', () => ({
  registerTaskAsync: jest.fn(async () => {}),
  unregisterTaskAsync: jest.fn(async () => {}),
  BackgroundFetchResult: { NoData: 1, NewData: 2, Failed: 3 },
}));

jest.mock('expo-notifications', () => ({
  setNotificationHandler: jest.fn(),
  getPermissionsAsync: jest.fn(async () => ({ granted: true })),
  requestPermissionsAsync: jest.fn(async () => ({ granted: true })),
  scheduleNotificationAsync: jest.fn(async () => 'test-notification-id'),
}));

jest.mock('expo-system-ui', () => ({
  setBackgroundColorAsync: jest.fn(async () => {}),
}));

jest.mock('@pchmn/expo-material3-theme', () => {
  const scheme = {
    primary: '#2563eb',
    onPrimary: '#ffffff',
    primaryContainer: '#e8effd',
    onPrimaryContainer: '#102033',
    secondary: '#bec8d6',
    onSecondary: '#28323f',
    secondaryContainer: '#3e4855',
    onSecondaryContainer: '#dae3f0',
    tertiary: '#3b82f6',
    onTertiary: '#ffffff',
    tertiaryContainer: '#1b3a6b',
    onTertiaryContainer: '#d3e3fd',
    background: '#f3f6fa',
    onBackground: '#102033',
    surface: '#ffffff',
    onSurface: '#102033',
    surfaceVariant: '#dce3eb',
    onSurfaceVariant: '#4f6276',
    outline: '#7a8a9a',
    outlineVariant: '#dce3eb',
    inverseSurface: '#102033',
    inverseOnSurface: '#edf3f9',
    inversePrimary: '#8ab4f8',
    error: '#c2410c',
    onError: '#ffffff',
    errorContainer: '#ffdad6',
    onErrorContainer: '#93000a',
    shadow: '#10203316',
    scrim: '#10203347',
    surfaceDisabled: '#ffffff61',
    onSurfaceDisabled: '#10203361',
    backdrop: '#10203347',
    surfaceContainer: '#eef3f8',
    surfaceContainerLow: '#edf2f8',
    surfaceContainerLowest: '#ffffff',
    surfaceContainerHigh: '#ffffff',
    surfaceContainerHighest: '#e7ecf4',
    surfaceBright: '#ffffff',
    surfaceDim: '#f3f6fa',
    surfaceTint: '#2563eb',
    elevation: {
      level0: 'transparent',
      level1: '#ffffff',
      level2: '#eef3f8',
      level3: '#edf2f8',
      level4: '#e7ecf4',
      level5: '#dce3eb',
    },
  };
  const darkScheme = {
    ...scheme,
    background: '#0b0e11',
    onBackground: '#edf3f9',
    surface: '#161d26',
    onSurface: '#edf3f9',
    onSurfaceVariant: '#98a6b5',
    outline: '#6f7d8c',
    outlineVariant: '#2a3442',
    surfaceContainer: '#1b2530',
    surfaceContainerLow: '#12181f',
    surfaceContainerLowest: '#0b0e11',
    surfaceContainerHigh: '#212d3a',
    surfaceContainerHighest: '#2a3442',
    primaryContainer: '#1e2a3d',
    scrim: '#05080cb8',
    shadow: '#00000088',
  };
  const theme = { light: scheme, dark: darkScheme };
  return {
    __esModule: true,
    isDynamicThemeSupported: false,
    createMaterial3Theme: jest.fn(() => theme),
    useMaterial3Theme: jest.fn(() => ({
      theme,
      updateTheme: jest.fn(),
      resetTheme: jest.fn(),
    })),
  };
});

jest.mock('@react-native-async-storage/async-storage', () =>
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- jest mock factory
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

jest.mock('@react-native-firebase/crashlytics', () => {
  const crashlytics = jest.fn(() => ({
    log: jest.fn(),
    recordError: jest.fn(),
    setCrashlyticsCollectionEnabled: jest.fn(async () => {}),
  }));
  return { __esModule: true, default: crashlytics };
});

jest.mock('@react-native-firebase/app', () => ({
  __esModule: true,
  default: {},
}));

jest.mock('@microsoft/react-native-clarity', () => ({
  initialize: jest.fn(),
  pause: jest.fn(async () => true),
  resume: jest.fn(async () => true),
  isPaused: jest.fn(async () => false),
}));

jest.mock('expo-application', () => ({
  nativeApplicationVersion: '1.0.0',
  nativeBuildVersion: '1',
  applicationId: 'com.eyex.australianrates',
}));

jest.mock('expo-device', () => ({
  platformApiLevel: 34,
  isSideLoadingEnabledAsync: jest.fn(async () => false),
}));

jest.mock('expo-intent-launcher', () => ({
  startActivityAsync: jest.fn(async () => {}),
}));

jest.mock('expo-file-system/legacy', () => ({
  cacheDirectory: 'file:///cache/',
  documentDirectory: 'file:///docs/',
  EncodingType: { Base64: 'base64' },
  deleteAsync: jest.fn(async () => {}),
  makeDirectoryAsync: jest.fn(async () => {}),
  moveAsync: jest.fn(async () => {}),
  writeAsStringAsync: jest.fn(async () => {}),
  createDownloadResumable: jest.fn(() => ({
    downloadAsync: jest.fn(async () => ({ uri: 'file:///cache/app-update.apk' })),
  })),
  getContentUriAsync: jest.fn(async () => 'content://test/app-update.apk'),
  getInfoAsync: jest.fn(async () => ({ exists: false })),
  readAsStringAsync: jest.fn(async () => ''),
}));
