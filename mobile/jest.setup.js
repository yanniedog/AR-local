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
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- jest mock factory
  const { createMaterial3Theme } = jest.requireActual('@pchmn/expo-material3-theme');
  const theme = createMaterial3Theme('#2563eb');
  return {
    __esModule: true,
    isDynamicThemeSupported: false,
    createMaterial3Theme,
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
