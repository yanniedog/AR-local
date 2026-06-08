// Mock native-only Expo modules so unit tests (pure logic) can import data modules
// without a native runtime. The app uses the real modules on device.
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
