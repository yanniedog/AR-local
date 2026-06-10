import React from 'react';
import renderer from 'react-test-renderer';

import { ChartErrorBoundary } from '../src/components/ChartErrorBoundary';
import { debugLog } from '../src/lib/debugLog';

function Boom(): React.ReactElement {
  throw new Error('svg render boom');
}

describe('ChartErrorBoundary', () => {
  it('logs render failures and shows fallback copy', () => {
    const errorSpy = jest.spyOn(debugLog, 'error').mockImplementation(() => {});
    const flushSpy = jest.spyOn(debugLog, 'flushToFile').mockResolvedValue(undefined);

    let tree!: renderer.ReactTestRenderer;
    renderer.act(() => {
      tree = renderer.create(
        <ChartErrorBoundary name="BankHistoryChart">
          <Boom />
        </ChartErrorBoundary>,
      );
    });

    expect(tree.root.findByProps({ children: 'History chart unavailable.' })).toBeTruthy();
    expect(errorSpy).toHaveBeenCalledWith(
      'BankHistoryChart',
      expect.stringContaining('render failed: svg render boom'),
    );
    expect(flushSpy).toHaveBeenCalled();

    errorSpy.mockRestore();
    flushSpy.mockRestore();
  });
});
