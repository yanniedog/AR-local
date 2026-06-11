import AsyncStorage from '@react-native-async-storage/async-storage';

import {
  logoUriFor,
  parseRegisterPayload,
  useRegisterLogosStore,
} from '../src/lib/registerLogos';

jest.mock('@react-native-async-storage/async-storage', () =>
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

describe('registerLogos', () => {
  it('parses renderable logoUri entries from register JSON', () => {
    const logos = parseRegisterPayload({
      data: [
        { brandName: 'MyState Bank', logoUri: 'https://mystate.com.au/logo.png' },
        { brandName: 'SVG Only', logoUri: 'https://example.com/logo.svg' },
        { brandName: 'Bad', logoUri: 'http://insecure.com/x.png' },
      ],
    });
    expect(logos).toEqual({ 'mystate bank': 'https://mystate.com.au/logo.png' });
  });

  it('matches provider names with suffix stripping', () => {
    const register = {
      'mystate bank': 'https://mystate.com.au/logo.png',
      'ing bank australia ltd': 'https://ing.com/logo.png',
      'bank australia': 'https://bankaust.com/logo.png',
    };
    expect(logoUriFor('MyState Bank Limited', register)).toBe('https://mystate.com.au/logo.png');
    expect(logoUriFor('ING BANK (Australia) Ltd', register)).toBe('https://ing.com/logo.png');
    expect(logoUriFor('Bank Australia', register)).toBe('https://bankaust.com/logo.png');
  });

  it('falls back to stale AsyncStorage cache when fetch fails', async () => {
    const store = useRegisterLogosStore.getState();
    useRegisterLogosStore.setState({ logos: {}, loaded: false, inflight: null });
    await AsyncStorage.clear();

    const stale = {
      savedAt: Date.now() - 8 * 24 * 3600 * 1000,
      logos: { 'mystate bank': 'https://mystate.com.au/logo.png' },
    };
    await AsyncStorage.setItem('ar.registerLogos.v1', JSON.stringify(stale));

    const originalFetch = global.fetch;
    global.fetch = jest.fn().mockRejectedValue(new Error('register down'));

    await store.ensure();

    expect(useRegisterLogosStore.getState().logos).toEqual(stale.logos);
    global.fetch = originalFetch;
  });
});
