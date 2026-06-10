import { debugLog } from '../src/lib/debugLog';
import {
  checkDrillOutcome, DEGRADE_TAG, logDegradation, logNavDeadDrill, logStoreRefreshSkipped,
  markDrillAttempt, resetDegradationStateForTests, summarizeUrl,
} from '../src/lib/degradationLog';
import { setDiagnosticsEnabled, setObservabilityDepsForTests } from '../src/lib/observability';

describe('degradationLog', () => {
  beforeEach(async () => {
    setObservabilityDepsForTests(null);
    await setDiagnosticsEnabled(true);
    debugLog.clear();
    resetDegradationStateForTests();
  });

  it('summarizeUrl strips query strings and truncates', () => {
    const out = summarizeUrl(`https://example.com/${'a'.repeat(200)}?token=secret`);
    expect(out).not.toContain('token=secret');
    expect(out.length).toBeLessThanOrEqual(120);
  });

  it('gates verbose info logs when diagnostics disabled', async () => {
    await setDiagnosticsEnabled(false);
    logDegradation('info', 'nav.tabNoOp', { tab: 'browse' });
    expect(debugLog.getText()).toBe('');
  });

  it('always logs warn events even when diagnostics disabled', async () => {
    await setDiagnosticsEnabled(false);
    logStoreRefreshSkipped('already_refreshing');
    expect(debugLog.getText()).toContain(`degrade: store.refreshSkipped reason=already_refreshing`);
  });

  it('confirms drill when path matches after attempt', () => {
    markDrillAttempt('Mortgage', ['fixed', 'owner']);
    checkDrillOutcome('Mortgage', ['fixed', 'owner']);
    expect(debugLog.getText()).toContain('nav.drillConfirmed');
    expect(debugLog.getText()).not.toContain('nav.deadDrill');
  });

  it('detects dead drill after timeout when path never deepens', () => {
    jest.useFakeTimers();
    markDrillAttempt('Mortgage', ['fixed', 'owner']);
    checkDrillOutcome('Mortgage', ['fixed']);
    jest.advanceTimersByTime(2000);
    expect(debugLog.getText()).toContain('nav.deadDrill');
    jest.useRealTimers();
  });

  it('logNavDeadDrill formats paths', () => {
    logNavDeadDrill({ section: 'Mortgage', expectedPath: ['a', 'b'], actualPath: ['a'] });
    expect(debugLog.getText()).toContain('expected=a.b');
    expect(debugLog.getText()).toContain('actual=a');
  });
});
