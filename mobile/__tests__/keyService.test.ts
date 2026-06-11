import { getAuth } from '@react-native-firebase/auth';
import * as SecureStore from 'expo-secure-store';

import { fetchContentKeys, isKeyServiceConfigured, syncContentKeys } from '../src/lib/keyService';
import { clearKeyCacheForTests, resolvePayloadKeyHex, storePayloadKeyHex } from '../src/lib/keyVault';

const KEY_HEX = 'ab'.repeat(32);
const URL = 'https://example.com/issueContentKeys';

function mockFetchOnce(status: number, body: unknown): jest.Mock {
  const mock = jest.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }));
  (global as { fetch: unknown }).fetch = mock;
  return mock;
}

describe('keyService', () => {
  beforeEach(async () => {
    clearKeyCacheForTests();
    await SecureStore.deleteItemAsync('ar.payload.deckey');
    (getAuth() as { currentUser: unknown }).currentUser = {
      getIdToken: jest.fn(async () => 'test-token'),
    };
  });

  it('is dormant without a configured URL', async () => {
    expect(isKeyServiceConfigured()).toBe(false);
    await expect(fetchContentKeys()).rejects.toThrow(/not configured/);
    expect(await syncContentKeys()).toBe(false);
  });

  it('sends the ID token and stores the issued key in the vault', async () => {
    const fetchMock = mockFetchOnce(200, {
      result: {
        tier: 'full',
        keys: [{ scope: 'full', alg: 'aes-256-gcm', key_id: 'deadbeef', key_hex: KEY_HEX }],
      },
    });
    expect(await syncContentKeys(URL)).toBe(true);
    const [, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      { headers: Record<string, string> },
    ];
    expect(init.headers.Authorization).toBe('Bearer test-token');
    expect(await resolvePayloadKeyHex()).toBe(KEY_HEX);
  });

  it('surfaces the callable error message', async () => {
    mockFetchOnce(429, { error: { message: 'Daily key-issuance limit reached' } });
    await expect(fetchContentKeys(URL)).rejects.toThrow(/limit reached/);
  });

  it('sync returns false (and stores nothing) on unusable keys', async () => {
    mockFetchOnce(200, {
      result: {
        tier: 'full',
        keys: [{ scope: 'full', alg: 'aes-256-gcm', key_id: 'x', key_hex: 'short' }],
      },
    });
    expect(await syncContentKeys(URL)).toBe(false);
    expect(await resolvePayloadKeyHex()).toBe('');
  });

  it('skips the network entirely when the vault already holds a key', async () => {
    const fetchMock = mockFetchOnce(200, {});
    await storePayloadKeyHex('cd'.repeat(32));
    expect(await syncContentKeys(URL)).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
    // force bypasses the guard (rotation path).
    mockFetchOnce(200, {
      result: { tier: 'full', keys: [{ scope: 'full', alg: 'aes-256-gcm', key_id: 'k', key_hex: KEY_HEX }] },
    });
    expect(await syncContentKeys(URL, { force: true })).toBe(true);
    expect(await resolvePayloadKeyHex()).toBe(KEY_HEX);
  });

  it('requires a signed-in user', async () => {
    (getAuth() as { currentUser: unknown }).currentUser = null;
    mockFetchOnce(200, {});
    await expect(fetchContentKeys(URL)).rejects.toThrow(/sign in/i);
  });
});
