import { debugLog } from '../src/lib/debugLog';
import {
  checkDrillOutcome, logDegradation, logNavDeadDrill, logStoreRefreshSkipped,
  markDrillAttempt, resetDegradationStateForTests, runStoreRetry, summarizeUrl,
} from '../src/lib/degradationLog';
import { setDiagnosticsEnabled, setObservabilityDepsForTests } from '../src/lib/observability';

describe('degradationLog', () => {
  beforeEach(async () => {
    setObservabilityDepsForTests(null);
    await setDiagnosticsEnabled(true);
    debugLog.clear();
    resetDegradationStateForTests();
  });

  afterEach(() => {
    resetDegradationStateForTests();
  });

  it('summarizeUrl strips query strings and truncates', () => {
    const out = summarizeUrl(`https://example.com/${'a'.repeat(200)}?token=secret`);
    expect(out).not.toContain('token=secret');
    expect(out.length).toBeLessThanOrEqual(120);
  });

  it('summarizeUrl handles non-URL strings without throwing', () => {
    expect(summarizeUrl('not a url?secret=1')).toBe('not a url');
  });

  it('gates verbose info logs when diagnostics disabled', async () => {
    await setDiagnosticsEnabled(false);
    logDegradation('info', 'nav.tabNoOp', { tab: 'browse' });
    expect(debugLog.getText()).toBe('');
  });

  it('always logs warn events even when diagnostics disabled', async () => {
    await setDiagnosticsEnabled(false);
    logStoreRefreshSkipped('already_refreshing');
    expect(debugLog.getText()).toContain('degrade: store.refreshSkipped reason=already_refreshing');
  });

  it('omits null/undefined/empty fields', () => {
    logDegradation('warn', 'evt', { keep: 'v', skipNull: null, skipUndef: undefined, skipEmpty: '' });
    expect(debugLog.getText()).toContain('evt keep=v');
    expect(debugLog.getText()).not.toContain('skipNull');
  });

  it('logNavDeadDrill formats paths', () => {
    logNavDeadDrill({ section: 'Mortgage', expectedPath: ['a', 'b'], actualPath: ['a'] });
    expect(debugLog.getText()).toContain('expected=a.b');
    expect(debugLog.getText()).toContain('actual=a');
  });

  it('a confirmed drill does NOT log deadDrill', () => {
    jest.useFakeTimers();
    markDrillAttempt('Mortgage', ['fixed', 'owner']);
    checkDrillOutcome('Mortgage', ['fixed', 'owner']);
    jest.advanceTimersByTime(2100);
    expect(debugLog.getText()).toContain('nav.drillConfirmed');
    expect(debugLog.getText()).not.toContain('nav.deadDrill');
    jest.useRealTimers();
  });

  it('logs deadDrill when no browse render confirms the attempt in time', () => {
    jest.useFakeTimers();
    markDrillAttempt('Mortgage', ['fixed', 'owner']);
    jest.advanceTimersByTime(2100);
    expect(debugLog.getText()).toContain('nav.deadDrill');
    expect(debugLog.getText()).toContain('expected=fixed.owner');
    jest.useRealTimers();
  });

  it('ignores interim renders before the path param lands', () => {
    jest.useFakeTimers();
    markDrillAttempt('TD', ['T12M']);
    checkDrillOutcome('TD', []); // section landed, path not yet
    checkDrillOutcome('TD', ['T12M']); // confirmed
    jest.advanceTimersByTime(2100);
    expect(debugLog.getText()).not.toContain('nav.deadDrill');
    jest.useRealTimers();
  });

  it('reports the last observed same-section path on dead drills', () => {
    jest.useFakeTimers();
    markDrillAttempt('TD', ['T12M']);
    checkDrillOutcome('TD', []); // path param dropped: never arrives
    jest.advanceTimersByTime(2100);
    expect(debugLog.getText()).toContain('nav.deadDrill');
    expect(debugLog.getText()).toContain('expected=T12M');
    expect(debugLog.getText()).toContain('actual=(root)');
    jest.useRealTimers();
  });

  it('only tracks the most recent attempt', () => {
    jest.useFakeTimers();
    markDrillAttempt('Mortgage', ['fixed']);
    markDrillAttempt('Mortgage', ['variable']);
    checkDrillOutcome('Mortgage', ['variable']);
    jest.advanceTimersByTime(2100);
    expect(debugLog.getText()).not.toContain('nav.deadDrill');
    jest.useRealTimers();
  });

  it('runStoreRetry logs start and success', async () => {
    await runStoreRetry('ensureThing', async () => {}, () => true);
    expect(debugLog.getText()).toContain('retry.start action=ensureThing');
    expect(debugLog.getText()).toContain('retry.success action=ensureThing');
  });

  it('runStoreRetry logs failure with detail', async () => {
    await runStoreRetry('ensureThing', async () => {}, () => false, () => 'HTTP 503');
    expect(debugLog.getText()).toContain('retry.failure action=ensureThing detail="HTTP 503"');
  });

  it('runStoreRetry logs failure when the action throws', async () => {
    await runStoreRetry('ensureThing', async () => { throw new Error('boom'); }, () => true);
    expect(debugLog.getText()).toContain('swallowed ctx=ensureThing error=boom');
    expect(debugLog.getText()).toContain('retry.failure action=ensureThing');
  });
});
