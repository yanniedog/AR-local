import type { CorePayload, Manifest } from '../src/types';
import { sampleCore, sampleManifest } from '../src/data/sample';

const mockReadBundle = jest.fn();
const mockReadMeta = jest.fn();
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
    readMeta: (...args: unknown[]) => mockReadMeta(...args),
    writeBundle: (...args: unknown[]) => mockWriteBundle(...args),
    readDetails: jest.fn(async () => null),
    writeDetails: jest.fn(async () => {}),
    updateMeta: jest.fn(async () => {}),
    clear: jest.fn(async () => {}),
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
    status: 'ready',
    refreshing: false,
    source: 'sample',
    manifest: remoteManifest,
    core: remoteCore,
    details: null,
    detailsLoading: false,
    error: null,
    offline: false,
    lastCheckedAt: null,
    payloadProgress: null,
    hydrated: true,
    prefs: useStore.getState().prefs,
    favorites: [],
  });
}

describe('store refresh lifecycle', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    resetStore();
    mockFetchManifest.mockResolvedValue(remoteManifest);
    mockWriteBundle.mockResolvedValue(undefined);
  });

  it('syncs source to remote on up-to-date refresh and clears refreshing', async () => {
    mockReadMeta.mockResolvedValue({
      manifest: remoteManifest,
      source: 'remote',
      savedAt: '2026-06-09T00:00:00Z',
      coreSha: remoteManifest.files.core.sha256,
      detailsSha: null,
    });
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

    const changed = await useStore.getState().refresh({});

    expect(changed).toBe(false);
    expect(mockDownloadCore).not.toHaveBeenCalled();
    const state = useStore.getState();
    expect(state.source).toBe('remote');
    expect(state.refreshing).toBe(false);
    expect(state.payloadProgress).toBeNull();
    expect(state.offline).toBe(false);
  });

  it('sets source remote after download and clears refreshing', async () => {
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

    const changed = await useStore.getState().refresh({});

    expect(changed).toBe(true);
    expect(useStore.getState().source).toBe('remote');
    expect(useStore.getState().refreshing).toBe(false);
    expect(useStore.getState().payloadProgress).toBeNull();
  });

  it('clears refreshing and flags offline on fetch failure', async () => {
    mockFetchManifest.mockRejectedValue(new Error('network error'));

    const changed = await useStore.getState().refresh({});

    expect(changed).toBe(false);
    const state = useStore.getState();
    expect(state.refreshing).toBe(false);
    expect(state.payloadProgress).toBeNull();
    expect(state.offline).toBe(true);
    expect(state.source).toBe('sample');
  });

  it('clears refreshing and flags offline on downloadCore failure', async () => {
    mockDownloadCore.mockRejectedValueOnce(new Error('download failure'));

    const changed = await useStore.getState().refresh({});

    expect(changed).toBe(false);
    const state = useStore.getState();
    expect(state.refreshing).toBe(false);
    expect(state.payloadProgress).toBeNull();
    expect(state.offline).toBe(true);
    expect(state.source).toBe('sample');
  });
});
