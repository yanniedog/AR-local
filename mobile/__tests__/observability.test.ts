import {
  bridgeLogToCrashlytics,
  initObservability,
  isDiagnosticsEnabled,
  setDiagnosticsEnabled,
  setObservabilityDepsForTests,
  type CrashlyticsLike,
  type ClarityLike,
} from '../src/lib/observability';

function makeMocks() {
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
  const crashlytics = jest.fn(() => crashlyticsApi);
  return { crashlytics, crashlyticsApi, clarityApi };
}

describe('observability', () => {
  const originalDev = (global as { __DEV__?: boolean }).__DEV__;
  const originalClarityId = process.env.EXPO_PUBLIC_CLARITY_PROJECT_ID;

  beforeEach(() => {
    jest.clearAllMocks();
    setObservabilityDepsForTests(null);
    void setDiagnosticsEnabled(true);
  });

  afterEach(() => {
    (global as { __DEV__?: boolean }).__DEV__ = originalDev;
    process.env.EXPO_PUBLIC_CLARITY_PROJECT_ID = originalClarityId;
    setObservabilityDepsForTests(null);
  });

  it('bridges info/warn/error to Crashlytics when enabled', () => {
    const { crashlytics, crashlyticsApi } = makeMocks();
    setObservabilityDepsForTests({ crashlytics, clarity: makeMocks().clarityApi });

    bridgeLogToCrashlytics('info', 'store', 'refresh ok');
    bridgeLogToCrashlytics('warn', 'store', 'prefs failed');
    bridgeLogToCrashlytics('error', 'payload', 'download failed');
    bridgeLogToCrashlytics('debug', 'store', 'skipped');

    expect(crashlyticsApi.log).toHaveBeenCalledTimes(3);
    expect(crashlyticsApi.recordError).toHaveBeenCalledTimes(1);
    expect(crashlyticsApi.log).toHaveBeenCalledWith('[ERROR] payload: download failed');
  });

  it('skips Crashlytics bridge when diagnostics disabled', async () => {
    const { crashlytics, crashlyticsApi } = makeMocks();
    setObservabilityDepsForTests({ crashlytics, clarity: makeMocks().clarityApi });
    await setDiagnosticsEnabled(false);

    bridgeLogToCrashlytics('error', 'app', 'boom');
    expect(crashlyticsApi.log).not.toHaveBeenCalled();
    expect(isDiagnosticsEnabled()).toBe(false);
  });

  it('initializes Clarity outside __DEV__ when project id is set', async () => {
    const { crashlytics, clarityApi } = makeMocks();
    setObservabilityDepsForTests({ crashlytics, clarity: clarityApi });
    (global as { __DEV__?: boolean }).__DEV__ = false;
    process.env.EXPO_PUBLIC_CLARITY_PROJECT_ID = 'test-clarity-project';

    await initObservability();

    expect(clarityApi.initialize).toHaveBeenCalledWith('test-clarity-project');
    expect(crashlytics().setCrashlyticsCollectionEnabled).toHaveBeenCalledWith(true);
  });

  it('pauses Clarity when diagnostics are disabled after init', async () => {
    const { crashlytics, clarityApi } = makeMocks();
    setObservabilityDepsForTests({ crashlytics, clarity: clarityApi });
    (global as { __DEV__?: boolean }).__DEV__ = false;
    process.env.EXPO_PUBLIC_CLARITY_PROJECT_ID = 'test-clarity-project';

    await initObservability();
    await setDiagnosticsEnabled(false);

    expect(clarityApi.pause).toHaveBeenCalled();
  });

  it('initializes Clarity when enabling diagnostics mid-session', async () => {
    const { crashlytics, clarityApi } = makeMocks();
    setObservabilityDepsForTests({ crashlytics, clarity: clarityApi });
    (global as { __DEV__?: boolean }).__DEV__ = false;
    process.env.EXPO_PUBLIC_CLARITY_PROJECT_ID = 'test-clarity-project';

    await setDiagnosticsEnabled(false);
    await setDiagnosticsEnabled(true);

    expect(clarityApi.initialize).toHaveBeenCalledWith('test-clarity-project');
    expect(clarityApi.resume).not.toHaveBeenCalled();
  });
});
