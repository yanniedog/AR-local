import { resolveOfflineBanner } from '../src/components/bannerState';
import type { PayloadProgressSnapshot } from '../src/data/downloadProgress';

const progress: PayloadProgressSnapshot = {
  phase: 'download',
  fileName: 'core.gz',
  bytesReceived: 1024,
  totalBytes: 4096,
  startedAt: Date.now(),
};

describe('resolveOfflineBanner', () => {
  it('hides when live remote data is online', () => {
    expect(resolveOfflineBanner('remote', false, false, null).mode).toBe('hidden');
  });

  it('shows offline banner for cached remote data', () => {
    const view = resolveOfflineBanner('remote', true, false, null);
    expect(view.mode).toBe('offline-cached');
    expect(view.message).toContain('last downloaded rates');
  });

  it('shows connecting while upgrading bundled sample', () => {
    const view = resolveOfflineBanner('sample', false, true, progress);
    expect(view.mode).toBe('connecting');
    expect(view.showLiveProgress).toBe(true);
    expect(view.message).toContain('connecting');
  });

  it('shows connecting copy before first progress event', () => {
    const view = resolveOfflineBanner('sample', false, true, null);
    expect(view.mode).toBe('connecting');
    expect(view.showLiveProgress).toBe(false);
  });

  it('hides stuck connecting state after refresh completes on sample while online', () => {
    expect(resolveOfflineBanner('sample', false, false, null).mode).toBe('hidden');
  });

  it('shows offline sample copy when upgrade failed', () => {
    const view = resolveOfflineBanner('sample', true, false, null);
    expect(view.mode).toBe('offline-sample');
    expect(view.message).toContain('bundled sample');
  });
});
