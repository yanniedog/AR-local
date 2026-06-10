import { Platform } from 'react-native';

import {
  getTabBarContentHeight,
  IOS_TAB_BAR_HEIGHT,
  M3_NAV_BAR_HEIGHT,
} from '../src/lib/androidChrome';

describe('getTabBarContentHeight', () => {
  const originalOS = Platform.OS;

  afterEach(() => {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: originalOS });
  });

  it('returns M3 height on Android', () => {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: 'android' });
    expect(getTabBarContentHeight()).toBe(M3_NAV_BAR_HEIGHT);
  });

  it('returns iOS default height on iOS', () => {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: 'ios' });
    expect(getTabBarContentHeight()).toBe(IOS_TAB_BAR_HEIGHT);
  });
});
