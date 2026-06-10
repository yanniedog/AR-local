#!/usr/bin/env node
import assert from 'node:assert/strict';
import test from 'node:test';

import {
  getAuthorizedUserAccessToken,
  parseAuthorizedUserJson,
} from './google-user-oauth-auth.mjs';

test('parseAuthorizedUserJson validates required refresh credentials', () => {
  assert.throws(
    () => parseAuthorizedUserJson('{"client_id":"id"}'),
    /missing client_secret/,
  );
  assert.equal(
    parseAuthorizedUserJson(
      '{"type":"authorized_user","client_id":"id","client_secret":"secret","refresh_token":"refresh"}',
    ).refresh_token,
    'refresh',
  );
});

test('getAuthorizedUserAccessToken exchanges a refresh token', async () => {
  const originalFetch = global.fetch;
  let submitted = '';
  global.fetch = async (_url, init) => {
    submitted = String(init?.body);
    return {
      ok: true,
      json: async () => ({ access_token: 'access-token' }),
    };
  };

  try {
    const token = await getAuthorizedUserAccessToken({
      client_id: 'id',
      client_secret: 'secret',
      refresh_token: 'refresh',
    });
    assert.equal(token, 'access-token');
    assert.match(submitted, /grant_type=refresh_token/);
    assert.match(submitted, /refresh_token=refresh/);
  } finally {
    global.fetch = originalFetch;
  }
});
