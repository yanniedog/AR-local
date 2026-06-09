import core from '../assets/sample/core.json';
import { selectBankHistoryChartModel } from '../src/data/historySelectors';
import { DEFAULT_PREFS, useStore } from '../src/data/store';
import type { CorePayload } from '../src/types';

const sample = core as CorePayload;

jest.mock('@react-native-async-storage/async-storage', () =>
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- jest mock factory
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

describe('showHistoryRibbon pref', () => {
  beforeEach(() => {
    useStore.setState({ prefs: { ...DEFAULT_PREFS }, hydrated: true });
  });

  it('defaults to false', () => {
    expect(DEFAULT_PREFS.showHistoryRibbon).toBe(false);
    expect(useStore.getState().prefs.showHistoryRibbon).toBe(false);
  });

  it('shows chart only when pref is on and history model exists', () => {
    const model = selectBankHistoryChartModel({ core: sample }, 'Mortgage');
    expect(model).not.toBeNull();

    const visible = (show: boolean) => show && model !== null;
    expect(visible(false)).toBe(false);

    useStore.getState().setPref('showHistoryRibbon', true);
    expect(visible(useStore.getState().prefs.showHistoryRibbon)).toBe(true);
  });
});
