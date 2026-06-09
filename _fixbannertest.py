from pathlib import Path
p = Path("mobile/__tests__/bannerState.test.ts")
t = p.read_text(encoding="utf-8")
t = t.replace(
"""  it('prefers offline copy when refresh runs while offline on sample', () => {
    const view = resolveOfflineBanner('sample', true, true, null);
    expect(view.mode).toBe('offline-sample');
    expect(view.message).toBe(
      'Offline — showing bundled sample data; latest data will load once you reconnect.',
    );
  });

  it('shows connecting once retry progress arrives while offline flag is still set', () => {
    const view = resolveOfflineBanner('sample', true, true, progress);
    expect(view.mode).toBe('connecting');
    expect(view.showLiveProgress).toBe(true);
  });""",
"""  it('shows connecting while retrying sample upgrade even if offline flag is still set', () => {
    const view = resolveOfflineBanner('sample', true, true, progress);
    expect(view.mode).toBe('connecting');
    expect(view.showLiveProgress).toBe(true);
  });

  it('shows connecting copy during offline-flagged retry before progress events', () => {
    const view = resolveOfflineBanner('sample', true, true, null);
    expect(view.mode).toBe('connecting');
    expect(view.showLiveProgress).toBe(false);
  });""")
p.write_text(t, encoding="utf-8")
print("banner tests ok")
