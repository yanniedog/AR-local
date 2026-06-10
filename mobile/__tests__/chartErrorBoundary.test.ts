import { ChartErrorBoundary } from '../src/components/ChartErrorBoundary';
import { debugLog } from '../src/lib/debugLog';

describe('ChartErrorBoundary', () => {
  it('logs render failures without a redundant explicit flush', () => {
    const errorSpy = jest.spyOn(debugLog, 'error').mockImplementation(() => {});
    const flushSpy = jest.spyOn(debugLog, 'flushToFile').mockResolvedValue(undefined);
    const boundary = new ChartErrorBoundary({ name: 'BankHistoryChart', children: null });
    boundary.componentDidCatch(new Error('svg render boom'), { componentStack: '\n    in Boom' });

    expect(errorSpy).toHaveBeenCalledWith(
      'BankHistoryChart',
      expect.stringContaining('render failed: svg render boom'),
    );
    expect(flushSpy).not.toHaveBeenCalled();

    errorSpy.mockRestore();
    flushSpy.mockRestore();
  });

  it('renders children while no error has been captured', () => {
    const child = 'chart contents';
    const boundary = new ChartErrorBoundary({ name: 'BankHistoryChart', children: child });

    expect(boundary.render()).toBe(child);
  });

  it('getDerivedStateFromError captures the error', () => {
    const err = new Error('boom');
    expect(ChartErrorBoundary.getDerivedStateFromError(err)).toEqual({ error: err });
  });
});
