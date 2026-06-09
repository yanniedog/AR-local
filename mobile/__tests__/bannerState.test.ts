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

  it('shows sample warning when live refresh was skipped while online', () => {
    const view = resolveOfflineBanner('sample', false, false, null);
    expect(view.mode).toBe('offline-sample');
    expect(view.message).toBe('Showing bundled sample data.');
  });

  it('shows offline sample copy when upgrade failed', () => {
    const view = resolveOfflineBanner('sample', true, false, null);
    expect(view.mode).toBe('offline-sample');
    expect(view.message).toContain('bundled sample');
  });

  it('shows connecting while retrying sample upgrade even if offline flag is still set', () => {
    const view = resolveOfflineBanner('sample', true, true, progress);
    expect(view.mode).toBe('connecting');
    expect(view.showLiveProgress).toBe(true);
  });

  it('shows connecting copy during offline-flagged retry before progress events', () => {
    const view = resolveOfflineBanner('sample', true, true, null);
    expect(view.mode).toBe('connecting');
    expect(view.showLiveProgress).toBe(false);
  });
});
