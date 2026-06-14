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
const mockDownloadBankInsights = jest.fn();
const mockReadHistoryBanks = jest.fn();
const mockReadBankInsights = jest.fn();
const mockClearHistoryBanks = jest.fn(async () => {});
const mockSyncHistoryFromDailyPayloads = jest.fn();
const mockReadProductHistory = jest.fn();
const mockWriteProductHistory = jest.fn();
const mockSyncProductHistoryFromDailyPayloads = jest.fn();

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
    readBankInsights: (...args: unknown[]) => mockReadBankInsights(...args),
    writeBankInsights: jest.fn(async () => {}),
    clearBankInsights: jest.fn(async () => {}),
    readProductHistory: (...args: unknown[]) => mockReadProductHistory(...args),
    writeProductHistory: (...args: unknown[]) => mockWriteProductHistory(...args),
    clearProductHistory: jest.fn(async () => {}),
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
  downloadBankInsights: (...args: unknown[]) => mockDownloadBankInsights(...args),
}));

jest.mock('../src/data/historyDaily', () => {
  const actual = jest.requireActual('../src/data/historyDaily') as object;
  return {
    ...actual,
    syncHistoryFromDailyPayloads: (...args: unknown[]) => mockSyncHistoryFromDailyPayloads(...args),
  };
});

jest.mock('../src/data/productHistory', () => {
  const actual = jest.requireActual('../src/data/productHistory') as object;
  return {
    ...actual,
    syncProductHistoryFromDailyPayloads: (...args: unknown[]) =>
      mockSyncProductHistoryFromDailyPayloads(...args),
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
    bank_history: {
      name: 'bank-history.json.gz',
      bytes: 3000,
      sha256: 'bank-history-sha',
      url: 'https://example.com/bank-history.json.gz',
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
    bankInsights: null,
    bankInsightsError: null,
    productHistory: null,
    productHistoryError: null,
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
    mockReadProductHistory.mockResolvedValue(null);
    mockWriteProductHistory.mockResolvedValue(undefined);
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
    expect(mockDownloadBankInsights).not.toHaveBeenCalled();
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

  it('ensureHistoryBanks downloads the compact asset before daily fallback', async () => {
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
    mockDownloadHistoryBanks.mockResolvedValue({
      historyBanks: {
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
      },
    });

    await store.getState().ensureHistoryBanks();

    expect(mockDownloadHistoryBanks).toHaveBeenCalledTimes(1);
    expect(mockSyncHistoryFromDailyPayloads).not.toHaveBeenCalled();
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

  it('turning history ribbon off keeps the compact cache warm and clears its error', () => {
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
    expect(store.getState().historyBanks).not.toBeNull();
    expect(store.getState().historyBanksError).toBeNull();
  });

  it('turning history ribbon on does not start a payload download', () => {
    store.setState({ prefs: proPrefs });

    store.getState().setPref('showHistoryRibbon', true);

    expect(store.getState().prefs.showHistoryRibbon).toBe(true);
    expect(mockDownloadHistoryBanks).not.toHaveBeenCalled();
    expect(mockSyncHistoryFromDailyPayloads).not.toHaveBeenCalled();
  });

  it('ensureProductHistory rechecks for newly indexed dates even when the core revision is unchanged', async () => {
    const cached = {
      schema_version: 2,
      run_date: remoteCore.run_date,
      core_sha: remoteManifest.files.core.sha256,
      run_dates: [remoteCore.run_date],
      products: { product: [0.05] },
    };
    store.setState({
      prefs: historyRibbonPrefs,
      source: 'remote',
      manifest: remoteManifest,
      core: remoteCore,
      productHistory: cached,
    });
    mockSyncProductHistoryFromDailyPayloads.mockResolvedValue(cached);

    await store.getState().ensureProductHistory();

    expect(mockSyncProductHistoryFromDailyPayloads).toHaveBeenCalledTimes(1);
  });

  it('ensureProductHistory does not install a result from a superseded core revision', async () => {
    let finishOldSync!: (value: unknown) => void;
    const oldSync = new Promise((resolve) => {
      finishOldSync = resolve;
    });
    const oldHistory = {
      schema_version: 2,
      run_date: remoteCore.run_date,
      core_sha: remoteManifest.files.core.sha256,
      run_dates: [remoteCore.run_date],
      products: { old: [0.05] },
    };
    store.setState({
      prefs: historyRibbonPrefs,
      source: 'remote',
      manifest: remoteManifest,
      core: remoteCore,
      productHistory: null,
    });
    mockSyncProductHistoryFromDailyPayloads.mockReturnValueOnce(oldSync);

    const pending = store.getState().ensureProductHistory();
    store.setState({
      manifest: {
        ...remoteManifest,
        files: {
          ...remoteManifest.files,
          core: { ...remoteManifest.files.core, sha256: 'new-core-sha' },
        },
      },
      productHistory: null,
    });
    finishOldSync(oldHistory);
    await pending;

    expect(mockWriteProductHistory).not.toHaveBeenCalled();
    expect(store.getState().productHistory).toBeNull();
  });

  it('ensureProductHistory does not let an older same-revision sync overwrite a newer result', async () => {
    let finishOldSync!: (value: unknown) => void;
    let finishNewSync!: (value: unknown) => void;
    const oldSync = new Promise((resolve) => {
      finishOldSync = resolve;
    });
    const newSync = new Promise((resolve) => {
      finishNewSync = resolve;
    });
    const oldHistory = {
      schema_version: 2,
      run_date: remoteCore.run_date,
      core_sha: remoteManifest.files.core.sha256,
      run_dates: [remoteCore.run_date],
      products: { old: [0.05] },
    };
    const newHistory = {
      ...oldHistory,
      run_dates: ['2026-05-13', remoteCore.run_date],
      products: { new: [0.051, 0.05] },
    };
    store.setState({
      prefs: historyRibbonPrefs,
      source: 'remote',
      manifest: remoteManifest,
      core: remoteCore,
      productHistory: null,
    });
    mockSyncProductHistoryFromDailyPayloads
      .mockReturnValueOnce(oldSync)
      .mockReturnValueOnce(newSync);

    const older = store.getState().ensureProductHistory();
    const newer = store.getState().ensureProductHistory();
    finishNewSync(newHistory);
    await newer;
    finishOldSync(oldHistory);
    await older;

    expect(store.getState().productHistory).toEqual(newHistory);
    expect(mockWriteProductHistory).toHaveBeenCalledTimes(1);
    expect(mockWriteProductHistory).toHaveBeenCalledWith(JSON.stringify(newHistory));
  });

  it('ensureHistoryBanks no-ops when history ribbon pref is off', async () => {
    await store.getState().ensureHistoryBanks();
    expect(mockDownloadHistoryBanks).not.toHaveBeenCalled();
  });

  it('ensureBankInsights no-ops without Pro', async () => {
    await store.getState().ensureBankInsights();
    expect(mockDownloadBankInsights).not.toHaveBeenCalled();
  });

  it('ensureBankInsights downloads and installs the asset for Pro users', async () => {
    store.setState({
      prefs: proPrefs,
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
      bankInsightsSha: null,
    });
    const insights = {
      schema_version: 1,
      run_date: remoteCore.run_date,
      run_dates: ['2026-05-13', remoteCore.run_date],
      banks: {
        AlphaBank: { Mortgage: { median: [0.06, 0.059], best: [0.055, 0.054], count: [4, 4] } },
      },
      events: [
        {
          date: remoteCore.run_date,
          provider: 'AlphaBank',
          section: 'Mortgage',
          dir: 'cut',
          moved: 2,
          total: 4,
          avg_bps: -10,
        },
      ],
    };
    mockDownloadBankInsights.mockResolvedValue({ text: JSON.stringify(insights), bankInsights: insights });

    await store.getState().ensureBankInsights();

    expect(mockDownloadBankInsights).toHaveBeenCalledTimes(1);
    expect(store.getState().bankInsights?.events).toHaveLength(1);
    expect(store.getState().bankInsightsError).toBeNull();
  });

  it('ensureBankInsights surfaces an error and keeps state null when download fails', async () => {
    store.setState({
      prefs: proPrefs,
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
      bankInsightsSha: null,
    });
    mockDownloadBankInsights.mockRejectedValue(new Error('bank_history payload failed validation'));

    await store.getState().ensureBankInsights();

    expect(store.getState().bankInsights).toBeNull();
    expect(store.getState().bankInsightsError).toMatch(/validation/i);
  });

  it('ensureBankInsights reports unavailable when the manifest lacks the asset', async () => {
    const { bank_history: _omit, ...files } = remoteManifest.files;
    store.setState({
      prefs: proPrefs,
      source: 'remote',
      manifest: { ...remoteManifest, files } as Manifest,
      core: remoteCore,
    });

    await store.getState().ensureBankInsights();

    expect(mockDownloadBankInsights).not.toHaveBeenCalled();
    expect(store.getState().bankInsightsError).toMatch(/unavailable/i);
  });

  it('ensureBankInsights force bypasses fresh cache and re-downloads', async () => {
    const insights = {
      schema_version: 1,
      run_date: remoteCore.run_date,
      run_dates: [remoteCore.run_date],
      banks: {},
      events: [],
    };
    store.setState({
      prefs: proPrefs,
      source: 'remote',
      manifest: remoteManifest,
      core: remoteCore,
      bankInsights: insights,
      bankInsightsError: 'stale error',
    });
    mockReadMeta.mockResolvedValue({
      manifest: remoteManifest,
      source: 'remote',
      savedAt: '2026-06-09T00:00:00Z',
      coreSha: remoteManifest.files.core.sha256,
      bankInsightsSha: remoteManifest.files.bank_history!.sha256,
    });
    mockDownloadBankInsights.mockResolvedValue({
      text: JSON.stringify(insights),
      bankInsights: insights,
    });

    await store.getState().ensureBankInsights();
    expect(mockDownloadBankInsights).not.toHaveBeenCalled();

    await store.getState().ensureBankInsights({ force: true });
    expect(mockDownloadBankInsights).toHaveBeenCalledTimes(1);
    expect(store.getState().bankInsightsError).toBeNull();
  });

  it('retryBankInsights refreshes manifest when bank_history is missing then downloads', async () => {
    const { bank_history: _bankHistoryAsset, ...filesWithoutHistory } = remoteManifest.files;
    const manifestWithoutHistory = { ...remoteManifest, files: filesWithoutHistory } as Manifest;
    store.setState({
      prefs: proPrefs,
      source: 'remote',
      manifest: manifestWithoutHistory,
      core: remoteCore,
      bankInsights: null,
      bankInsightsError: 'bank history unavailable',
    });
    mockFetchManifest.mockResolvedValue(remoteManifest);
    mockDownloadCore.mockResolvedValue({ text: JSON.stringify(remoteCore), core: remoteCore });
    mockReadMeta.mockResolvedValue({
      manifest: remoteManifest,
      source: 'remote',
      savedAt: '2026-06-09T00:00:00Z',
      coreSha: remoteManifest.files.core.sha256,
      bankInsightsSha: null,
    });
    const insights = {
      schema_version: 1,
      run_date: remoteCore.run_date,
      run_dates: [remoteCore.run_date],
      banks: {
        AlphaBank: { Mortgage: { median: [0.06], best: [0.055], count: [4] } },
      },
      events: [],
    };
    mockDownloadBankInsights.mockResolvedValue({
      text: JSON.stringify(insights),
      bankInsights: insights,
    });

    await store.getState().retryBankInsights();

    expect(mockFetchManifest).toHaveBeenCalled();
    expect(mockDownloadBankInsights).toHaveBeenCalled();
    expect(store.getState().bankInsights?.banks.AlphaBank).toBeDefined();
    expect(store.getState().bankInsightsError).toBeNull();
  });
});
