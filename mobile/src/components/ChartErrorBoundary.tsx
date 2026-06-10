import React from 'react';

import { debugLog } from '../lib/debugLog';
import { AppText } from './ui';

type Props = {
  children: React.ReactNode;
  /** Short label for debugLog (e.g. BankHistoryChart). */
  name: string;
};

type State = { error: Error | null };

/** Catches render errors in chart subtrees so Home stays usable and debugLog records the fault. */
export class ChartErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    const frame = info.componentStack?.split('\n').find((line) => line.trim())?.trim() ?? '';
    debugLog.error(this.props.name, `render failed: ${error.message}${frame ? ` @ ${frame}` : ''}`);
    void debugLog.flushToFile();
  }

  render(): React.ReactNode {
    if (this.state.error) {
      return (
        <AppText variant="tiny" color="textFaint">
          History chart unavailable.
        </AppText>
      );
    }
    return this.props.children;
  }
}
