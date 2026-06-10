import type { CorePayload, Manifest } from '../src/types';
import { shouldWarmDetails } from '../src/data/optionalPrefs';
import { sampleCore, sampleManifest } from '../src/data/sample';
import { DEFAULT_PREFS, useStore } from '../src/data/store';

const mockReadBundle = jest.fn();
const mockReadMeta = jest.fn();
const mockWriteBundle = jest.fn();
const mockFetchManifest = jest.fn();
const mockDownloadCore = jest.fn();
const mockDownloadDetails = jest.fn();
const mockDownloadSearchIndex = jest.fn();
const mockDownloadHistoryBanks = jest.fn();
const mockReadHistoryBanks = jest.fn();
const mockClearHistoryBanks = jest.fn(async () => {});
const mockSyncHistoryFromDailyPayloads = jest.fn();

jest.mock('@react-native-async-storage/async-storage', () =>
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- jest mock factory
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

jest.mock('expo-network', () => ({
  getNetworkStateAsync: jest.fn(async () => ({ type: 'WIFI' })),
  NetworkStateType: { WIFI: 'WIFI', CELLULAR: 'CELLULAR' },
}));

jest.mock('../src/data/cache', () => ({
  cache: {
    readBundle: (...args: unknown[]) => mockReadBundle(...args),
    readMeta: (...args: unknown[]) => mockReadMeta(...args),
    writeBundle: (...args: unknown[]) => mockWriteBundle(...args),
    readDetails: jest.fn(async () => null),
    writeDetails: jest.fn(async () => {}),
    readSearchIndex: jest.fn(async () => null),
    writeSearchIndex: jest.fn(async () => {}),
    readHistoryBanks: (...args: unknown[]) => mockReadHistoryBanks(...args),
    clearHistoryBanks: () => mockClearHistoryBanks(),
    writeHistoryBanks: jest.fn(async () => {}),
    updateMeta: jest.fn(async () => {}),
    clear: jest.fn(async () => {}),
  },
}));

jest.mock('../src/data/payload', () => ({
  fetchManifest: (...args: unknown[]) => mockFetchManifest(...args),
  downloadCore: (...args: unknown[]) => mockDownloadCore(...args),
  downloadDetails: (...args: unknown[]) => mockDownloadDetails(...args),
  downloadSearchIndex: (...args: unknown[]) => mockDownloadSearchIndex(...args),
  downloadHistoryBanks: (...args: unknown[]) => mockDownloadHistoryBanks(...args),
}));

jest.mock('../src/data/historyDaily', () => {
  const actual = jest.requireActual('../src/data/historyDaily') as object;
  return {
    ...actual,
    syncHistoryFromDailyPayloads: (...args: unknown[]) => mockSyncHistoryFromDailyPayloads(...args),
  };
});

// eslint-disable-next-line import/first -- store import must follow jest mocks
import { useStore as store } from '../src/data/store';
import { debugLog } from '../src/lib/debugLog';

const remoteManifest: Manifest = {
  ...sampleManifest,
  files: {
    ...sampleManifest.files,
    search_index: {
      name: 'search-index.json.gz',
      bytes: 1000,
      sha256: 'search-sha',
      url: 'https://example.com/search-index.json.gz',
    },
    history_banks: {
      name: 'history-banks.json.gz',
      bytes: 2000,
      sha256: 'history-sha',
      url: 'https://example.com/history-banks.json.gz',
    },
  },
};
const remoteCore: CorePayload = sampleCore;

const proPrefs = { ...DEFAULT_PREFS, rateIntelligencePro: true };
const historyRibbonPrefs = { ...proPrefs, showHistoryRibbon: true };
const deepSearchPrefs = { ...proPrefs, enableDeepSearch: true };

function resetStore() {
  store.setState({
    status: 'ready',
    refreshing: false,
    source: 'sample',
    manifest: remoteManifest,
    core: remoteCore,
    details: null,
    searchIndex: null,
    historyBanks: null,
    historyBanksError: null,
    detailsLoading: false,
    error: null,
    offline: false,
    lastCheckedAt: null,
    payloadProgress: null,
    hydrated: true,
    prefs: { ...DEFAULT_PREFS },
    favorites: [],
    subscriptions: [],
  });
}

describe('optional feature prefs', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    resetStore();
    mockFetchManifest.mockResolvedValue(remoteManifest);
    mockWriteBundle.mockResolvedValue(undefined);
  });

  it('defaults deep search and history ribbon off', () => {
    expect(DEFAULT_PREFS.enableDeepSearch).toBe(false);
    expect(DEFAULT_PREFS.showHistoryRibbon).toBe(false);
  });

  it('shouldWarmDetails is false with default prefs', () => {
    expect(shouldWarmDetails(DEFAULT_PREFS, [])).toBe(false);
  });

  it('refresh does not download details or optional assets by default', async () => {
    mockReadMeta.mockResolvedValue({
      manifest: remoteManifest,
      source: 'sample',
      savedAt: '2026-06-08T00:00:00Z',
      coreSha: 'old-hash',
      detailsSha: null,
    });
    mockDownloadCore.mockResolvedValue({
      text: JSON.stringify(remoteCore),
      core: remoteCore,
    });

    await store.getState().refresh({});

    expect(mockDownloadDetails).not.toHaveBeenCalled();
    expect(mockDownloadSearchIndex).not.toHaveBeenCalled();
    expect(mockDownloadHistoryBanks).not.toHaveBeenCalled();
  });

  it('ensureSearchIndex downloads when deep search is enabled', async () => {
    store.setState({
      prefs: deepSearchPrefs,
      source: 'remote',
      manifest: remoteManifest,
      core: remoteCore,
    });
    mockReadMeta.mockResolvedValue({
      manifest: remoteManifest,
      source: 'remote',
      savedAt: '2026-06-09T00:00:00Z',
      coreSha: remoteManifest.files.core.sha256,
      detailsSha: null,
      searchIndexSha: null,
    });
    mockDownloadSearchIndex.mockResolvedValue({
      text: '{"schema_version":1,"run_date":"2026-05-19","products":{}}',
      searchIndex: { schema_version: 1, run_date: remoteCore.run_date, products: {} },
    });

    await store.getState().ensureSearchIndex();

    expect(mockDownloadSearchIndex).toHaveBeenCalled();
    expect(store.getState().searchIndex).not.toBeNull();
  });

  it('ensureSearchIndex no-ops when deep search is off', async () => {
    await store.getState().ensureSearchIndex();
    expect(mockDownloadSearchIndex).not.toHaveBeenCalled();
  });

  it('ensureHistoryBanks syncs daily payloads when history ribbon pref is on', async () => {
    const infoSpy = jest.spyOn(debugLog, 'info').mockImplementation(() => {});
    store.setState({
      prefs: historyRibbonPrefs,
      source: 'remote',
      manifest: remoteManifest,
      core: remoteCore,
      historyBanksError: 'previous error',
    });
    mockReadMeta.mockResolvedValue({
      manifest: remoteManifest,
      source: 'remote',
      savedAt: '2026-06-09T00:00:00Z',
      coreSha: remoteManifest.files.core.sha256,
      detailsSha: null,
      historyBanksSha: null,
    });
    global.fetch = jest.fn(async () => ({
      ok: true,
      json: async () => ({
        dates: ['2026-05-13', remoteCore.run_date],
        count: 2,
        min_date: '2026-05-13',
      }),
    })) as unknown as typeof fetch;
    mockSyncHistoryFromDailyPayloads.mockResolvedValue({
      schema_version: 1,
      run_date: remoteCore.run_date,
      run_dates: ['2026-05-13', remoteCore.run_date],
      sections: {
        Mortgage: {
          points: [
            { date: '2026-05-13', min: 0.03, max: 0.08, mean: 0.05, median: 0.05, count: 1 },
            {
              date: remoteCore.run_date,
              min: 0.031,
              max: 0.081,
              mean: 0.051,
              median: 0.051,
              count: 1,
            },
          ],
        },
      },
    });

    await store.getState().ensureHistoryBanks();

    expect(mockSyncHistoryFromDailyPayloads).toHaveBeenCalled();
    expect(mockDownloadHistoryBanks).not.toHaveBeenCalled();
    expect(store.getState().historyBanks?.run_dates).toHaveLength(2);
    expect(store.getState().historyBanksError).toBeNull();
    expect(infoSpy).toHaveBeenCalledWith(
      'store',
      expect.stringContaining(`ensureHistoryBanks ok run_date=${remoteCore.run_date}`),
    );
    infoSpy.mockRestore();
  });

  it('ensureHistoryBanks logs start and validation failure to debugLog', async () => {
    const infoSpy = jest.spyOn(debugLog, 'info').mockImplementation(() => {});
    const errorSpy = jest.spyOn(debugLog, 'error').mockImplementation(() => {});
    store.setState({
      prefs: historyRibbonPrefs,
      source: 'remote',
      manifest: remoteManifest,
      core: remoteCore,
    });
    mockSyncHistoryFromDailyPayloads.mockRejectedValue(new Error('daily sync failed'));
    global.fetch = jest.fn(async () => ({ ok: false })) as unknown as typeof fetch;
    mockReadMeta.mockResolvedValue({
      manifest: remoteManifest,
      source: 'remote',
      savedAt: '2026-06-09T00:00:00Z',
      coreSha: remoteManifest.files.core.sha256,
      detailsSha: null,
      historyBanksSha: null,
    });
    mockDownloadHistoryBanks.mockResolvedValue({
      text: '{"schema_version":1,"run_date":"2026-05-19","run_dates":[],"sections":{}}',
      historyBanks: {
        schema_version: 1,
        run_date: remoteCore.run_date,
        run_dates: [],
        sections: {},
      },
    });

    await store.getState().ensureHistoryBanks();

    expect(infoSpy).toHaveBeenCalledWith('store', 'ensureHistoryBanks start');
    expect(errorSpy).toHaveBeenCalledWith(
      'store',
      'ensureHistoryBanks rejected payload after download (validation failed)',
    );
    expect(store.getState().historyBanksError).toMatch(/validation/i);

    infoSpy.mockRestore();
    errorSpy.mockRestore();
  });

  it('ensureHistoryBanks records error when download validation fails', async () => {
    store.setState({
      prefs: historyRibbonPrefs,
      source: 'remote',
      manifest: remoteManifest,
      core: remoteCore,
    });
    mockSyncHistoryFromDailyPayloads.mockRejectedValue(new Error('daily sync failed'));
    global.fetch = jest.fn(async () => ({ ok: false })) as unknown as typeof fetch;
    mockReadMeta.mockResolvedValue({
      manifest: remoteManifest,
      source: 'remote',
      savedAt: '2026-06-09T00:00:00Z',
      coreSha: remoteManifest.files.core.sha256,
      detailsSha: null,
      historyBanksSha: null,
    });
    mockDownloadHistoryBanks.mockRejectedValue(new Error('history_banks payload failed validation'));

    await store.getState().ensureHistoryBanks();

    expect(store.getState().historyBanks).toBeNull();
    expect(store.getState().historyBanksError).toMatch(/validation/i);
  });


  it('ensureHistoryBanks discards invalid cached payload and clears cache', async () => {
    mockReadHistoryBanks.mockResolvedValue({ run_date: '2026-05-19', sections: { Mortgage: { points: 'bad' } } });
    store.setState({
      prefs: historyRibbonPrefs,
      source: 'remote',
      manifest: remoteManifest,
      core: remoteCore,
    });
    mockSyncHistoryFromDailyPayloads.mockRejectedValue(new Error('daily sync failed'));
    global.fetch = jest.fn(async () => ({ ok: false })) as unknown as typeof fetch;
    mockReadMeta.mockResolvedValue({
      manifest: remoteManifest,
      source: 'remote',
      savedAt: '2026-06-09T00:00:00Z',
      coreSha: remoteManifest.files.core.sha256,
      detailsSha: null,
      historyBanksSha: null,
    });

    await store.getState().ensureHistoryBanks();

    expect(mockClearHistoryBanks).toHaveBeenCalled();
    expect(store.getState().historyBanks).toBeNull();
    expect(mockDownloadHistoryBanks).toHaveBeenCalled();
  });

  it('turning history ribbon off clears historyBanks and historyBanksError', () => {
    store.setState({
      prefs: historyRibbonPrefs,
      historyBanks: {
        schema_version: 1,
        run_date: remoteCore.run_date,
        run_dates: [remoteCore.run_date],
        sections: {},
      },
      historyBanksError: 'some error',
    });

    store.getState().setPref('showHistoryRibbon', false);

    expect(store.getState().prefs.showHistoryRibbon).toBe(false);
    expect(store.getState().historyBanks).toBeNull();
    expect(store.getState().historyBanksError).toBeNull();
  });
  it('ensureHistoryBanks no-ops when history ribbon pref is off', async () => {
    await store.getState().ensureHistoryBanks();
    expect(mockDownloadHistoryBanks).not.toHaveBeenCalled();
  });
});
