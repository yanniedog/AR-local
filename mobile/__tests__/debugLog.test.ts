import AsyncStorage from '@react-native-async-storage/async-storage';
import * as FileSystem from 'expo-file-system/legacy';

// eslint-disable-next-line import/first -- imports after jest mocks
import {
  ANDROID_LOG_PATH_HINT,
  MAX_LOG_BYTES,
  MAX_LOG_LINES,
  RingBuffer,
  debugLog,
  formatEntry,
  formatLogUploadBody,
  installGlobalErrorHandlers,
  parseLogLine,
  redactSecrets,
  resetGlobalErrorHandlersForTests,
  uploadLogsToPasteRs,
} from '../src/lib/debugLog';
import {
  setDiagnosticsEnabled,
  setObservabilityDepsForTests,
  type CrashlyticsLike,
  type ClarityLike,
} from '../src/lib/observability';

const crashlyticsApi: CrashlyticsLike = {
  log: jest.fn(),
  recordError: jest.fn(),
  setCrashlyticsCollectionEnabled: jest.fn(async () => {}),
};

const clarityApi: ClarityLike = {
  initialize: jest.fn(),
  pause: jest.fn(async () => true),
  resume: jest.fn(async () => true),
};

describe('redactSecrets', () => {
  it('redacts EXPO_TOKEN and bearer tokens', () => {
    const input = 'auth EXPO_TOKEN=abc123 Bearer sk-live-xyz token=secretval';
    const out = redactSecrets(input);
    expect(out).not.toContain('abc123');
    expect(out).not.toContain('sk-live-xyz');
    expect(out).toContain('[REDACTED]');
  });
});

describe('RingBuffer', () => {
  it('evicts oldest lines when exceeding MAX_LOG_LINES', () => {
    const buf = new RingBuffer();
    for (let i = 0; i < MAX_LOG_LINES + 5; i++) {
      buf.append({
        ts: new Date().toISOString(),
        level: 'debug',
        tag: 't',
        message: `line-${i}`,
      });
    }
    expect(buf.size()).toBe(MAX_LOG_LINES);
    expect(buf.getText()).toContain(`line-${MAX_LOG_LINES + 4}`);
    expect(buf.getText()).not.toContain('line-0');
  });

  it('evicts by byte budget', () => {
    const buf = new RingBuffer();
    const chunk = 'x'.repeat(1024);
    const lines = Math.ceil(MAX_LOG_BYTES / (chunk.length + 40)) + 2;
    for (let i = 0; i < lines; i++) {
      buf.append({
        ts: new Date().toISOString(),
        level: 'info',
        tag: 'big',
        message: `${chunk}-${i}`,
      });
    }
    expect(buf.size()).toBeLessThan(lines);
    expect(buf.getText().length).toBeLessThanOrEqual(MAX_LOG_BYTES + 512);
  });
});

describe('formatLogUploadBody', () => {
  it('wraps entries with header metadata', () => {
    const body = formatLogUploadBody('2026-01-01T00:00:00.000Z [INFO] app: hi', {
      app: '1.0.0',
      lines: '1',
    });
    expect(body).toContain('# AR-local mobile debug log');
    expect(body).toContain('app=1.0.0');
    expect(body).toContain('[INFO] app: hi');
  });
});

describe('uploadLogsToPasteRs', () => {
  it('returns paste URL on 201', async () => {
    const mockFetch = jest.fn(async () => ({
      status: 201,
      text: async () => 'https://paste.rs/abc123',
    })) as unknown as typeof fetch;
    const result = await uploadLogsToPasteRs('hello', mockFetch);
    expect(result.url).toBe('https://paste.rs/abc123');
    expect(result.truncated).toBe(false);
    expect(mockFetch).toHaveBeenCalledWith(
      'https://paste.rs/',
      expect.objectContaining({ method: 'POST', body: 'hello' }),
    );
  });

  it('marks truncated on 206', async () => {
    const mockFetch = jest.fn(async () => ({
      status: 206,
      text: async () => 'https://paste.rs/partial',
    })) as unknown as typeof fetch;
    const result = await uploadLogsToPasteRs('big log', mockFetch);
    expect(result.truncated).toBe(true);
  });

  it('throws on error status', async () => {
    const mockFetch = jest.fn(async () => ({
      status: 429,
      text: async () => 'rate limited',
    })) as unknown as typeof fetch;
    await expect(uploadLogsToPasteRs('x', mockFetch)).rejects.toThrow(/upload failed/);
  });
});

describe('parseLogLine', () => {
  it('round-trips formatted entries', () => {
    const entry = {
      ts: '2026-01-01T00:00:00.000Z',
      level: 'info' as const,
      tag: 'app',
      message: 'bootstrap starting',
    };
    const parsed = parseLogLine(formatEntry(entry));
    expect(parsed).toEqual(entry);
  });
});

describe('persistent log file', () => {
  beforeEach(async () => {
    jest.clearAllMocks();
    setObservabilityDepsForTests({
      crashlytics: () => crashlyticsApi,
      clarity: clarityApi,
    });
    await setDiagnosticsEnabled(true);
    debugLog.clear();
    await AsyncStorage.clear();
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValue({ exists: false });
    (FileSystem.readAsStringAsync as jest.Mock).mockResolvedValue('');
  });

  afterEach(() => {
    setObservabilityDepsForTests(null);
  });

  it('writes log lines to the persistent file', async () => {
    debugLog.info('test', 'file persist');
    await debugLog.flushToFile();

    expect(FileSystem.makeDirectoryAsync).toHaveBeenCalledWith(
      'file:///docs/logs/',
      { intermediates: true },
    );
    expect(FileSystem.writeAsStringAsync).toHaveBeenCalled();
    const [path, contents] = (FileSystem.writeAsStringAsync as jest.Mock).mock.calls[0];
    expect(path).toBe('file:///docs/logs/ar-local.log');
    expect(contents).toContain('file persist');
    expect(contents).not.toContain('secret');
  });

  it('clear deletes the persistent log file', async () => {
    debugLog.info('test', 'before clear');
    await debugLog.flushToFile();
    debugLog.clear();

    expect(FileSystem.deleteAsync).toHaveBeenCalledWith(
      'file:///docs/logs/ar-local.log',
      { idempotent: true },
    );
  });

  it('restores tail from log file on startup', async () => {
    const line = formatEntry({
      ts: '2026-01-01T00:00:00.000Z',
      level: 'warn',
      tag: 'store',
      message: 'from disk',
    });
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValue({ exists: true });
    (FileSystem.readAsStringAsync as jest.Mock).mockResolvedValue(`${line}\n`);

    debugLog.clear();
    await debugLog.restoreFromStorage();
    expect(debugLog.getText()).toContain('from disk');
  });

  it('exposes Android scoped storage path hint', () => {
    expect(debugLog.getAndroidLogPathHint()).toBe(ANDROID_LOG_PATH_HINT);
    expect(ANDROID_LOG_PATH_HINT).toContain('com.eyex.australianrates');
  });
});

describe('debugLog integration', () => {
  beforeEach(async () => {
    jest.clearAllMocks();
    setObservabilityDepsForTests({
      crashlytics: () => crashlyticsApi,
      clarity: clarityApi,
    });
    await setDiagnosticsEnabled(true);
    debugLog.clear();
    await AsyncStorage.clear();
  });

  afterEach(() => {
    setObservabilityDepsForTests(null);
  });

  it('stores redacted lines and restores tail snapshot', async () => {
    debugLog.info('test', 'hello EXPO_TOKEN=secret');
    expect(debugLog.getText()).toContain('[REDACTED]');
    expect(debugLog.getText()).not.toContain('secret');

    debugLog.clear();
    expect(debugLog.getText()).toBe('');

    debugLog.info('test', 'persist me');
    await debugLog.flushToFile();

    await debugLog.restoreFromStorage();
    expect(debugLog.getText()).toContain('persist me');
  });

  it('forwards warn/error lines to Crashlytics', () => {
    debugLog.warn('store', 'prefs rehydrate failed');
    debugLog.error('payload', 'download failed');

    expect(crashlyticsApi.log).toHaveBeenCalledWith('[WARN] store: prefs rehydrate failed');
    expect(crashlyticsApi.log).toHaveBeenCalledWith('[ERROR] payload: download failed');
    expect(crashlyticsApi.recordError).toHaveBeenCalledTimes(1);
  });

  it('redacts secrets forwarded to Crashlytics', () => {
    debugLog.warn('test', 'hello EXPO_TOKEN=secret');

    expect(crashlyticsApi.log).toHaveBeenCalledWith('[WARN] test: hello EXPO_TOKEN=[REDACTED]');
    expect(crashlyticsApi.log).not.toHaveBeenCalledWith(expect.stringContaining('secret'));
  });

  it('installGlobalErrorHandlers forwards fatal errors to debugLog', () => {
    debugLog.clear();
    resetGlobalErrorHandlersForTests();
    const flushSpy = jest.spyOn(debugLog, 'flushToFile').mockResolvedValue(undefined);
    const g = global as typeof global & {
      ErrorUtils?: {
        getGlobalHandler?: () => (error: unknown, isFatal?: boolean) => void;
        setGlobalHandler?: (handler: (error: unknown, isFatal?: boolean) => void) => void;
      };
    };
    const previous = jest.fn();
    g.ErrorUtils = {
      getGlobalHandler: () => previous,
      setGlobalHandler: (handler) => {
        handler(new Error('ribbon blew up'), true);
      },
    };

    installGlobalErrorHandlers();

    expect(debugLog.getText()).toContain('[ERROR] global: fatal Error: ribbon blew up');
    expect(previous).toHaveBeenCalled();
    expect(flushSpy).not.toHaveBeenCalled();
    flushSpy.mockRestore();
  });
});
