import type { CorePayload, Manifest } from '../src/types';
import { sampleCore, sampleManifest } from '../src/data/sample';

const mockReadBundle = jest.fn();
const mockWriteBundle = jest.fn();
const mockFetchManifest = jest.fn();
const mockDownloadCore = jest.fn();

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
    readMeta: jest.fn(async () => null),
    writeBundle: (...args: unknown[]) => mockWriteBundle(...args),
    readDetails: jest.fn(async () => null),
    writeDetails: jest.fn(async () => {}),
    updateMeta: jest.fn(async () => {}),
    clear: jest.fn(async () => {}),
    readSearchIndex: jest.fn(async () => null),
    readHistoryBanks: jest.fn(async () => null),
    clearHistoryBanks: jest.fn(async () => {}),
  },
}));

jest.mock('../src/data/payload', () => ({
  fetchManifest: (...args: unknown[]) => mockFetchManifest(...args),
  downloadCore: (...args: unknown[]) => mockDownloadCore(...args),
  downloadDetails: jest.fn(),
}));

// eslint-disable-next-line import/first -- store import must follow jest mocks
import { useStore } from '../src/data/store';

const remoteManifest: Manifest = sampleManifest;
const remoteCore: CorePayload = sampleCore;

function resetStore() {
  useStore.setState({
    status: 'error',
    refreshing: false,
    source: 'sample',
    manifest: null,
    core: null,
    details: null,
    detailsLoading: false,
    error: 'network error',
    offline: true,
    lastCheckedAt: null,
    payloadProgress: null,
    hydrated: true,
    prefs: useStore.getState().prefs,
    favorites: [],
  });
}

describe('store error recovery', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    resetStore();
    mockWriteBundle.mockResolvedValue(undefined);
    mockFetchManifest.mockResolvedValue(remoteManifest);
    mockDownloadCore.mockResolvedValue({
      text: JSON.stringify(remoteCore),
      core: remoteCore,
    });
  });

  it('loadSampleFallback installs bundled sample and clears error', async () => {
    await useStore.getState().loadSampleFallback();
    const state = useStore.getState();
    expect(state.status).toBe('ready');
    expect(state.error).toBeNull();
    expect(state.core).toEqual(sampleCore);
    expect(state.source).toBe('sample');
    expect(mockWriteBundle).toHaveBeenCalled();
  });

  it('retryDataLoad bootstraps from cache then refreshes when bundle exists', async () => {
    mockReadBundle.mockResolvedValue({
      meta: {
        manifest: remoteManifest,
        source: 'remote',
        savedAt: '2026-06-09T00:00:00Z',
        coreSha: remoteManifest.files.core.sha256,
        detailsSha: null,
      },
      core: remoteCore,
    });
    await useStore.getState().retryDataLoad();
    const state = useStore.getState();
    expect(state.status).toBe('ready');
    expect(state.error).toBeNull();
    expect(state.core).toEqual(remoteCore);
    expect(mockFetchManifest).toHaveBeenCalled();
  });

  it('bootstrap sets error when sample seed write fails', async () => {
    useStore.setState({ status: 'idle', core: null, error: null });
    mockReadBundle.mockResolvedValue(null);
    mockWriteBundle.mockRejectedValueOnce(new Error('disk full'));
    await useStore.getState().bootstrap();
    const state = useStore.getState();
    expect(state.status).toBe('error');
    expect(state.error).toContain('disk full');
    expect(state.core).toBeNull();
  });
});
