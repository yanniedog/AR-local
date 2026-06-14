#!/usr/bin/env node
import assert from 'node:assert/strict';
import test from 'node:test';

import { pushHeadToMain } from './mobile-auto-release-commit.mjs';

function result(status = 0, stdout = '', stderr = '') {
  return { status, stdout, stderr };
}

test('clean invocation leaves an older stash untouched', () => {
  const calls = [];
  const responses = [
    result(0, 'old-stash\n'),
    result(0, 'No local changes to save\n'),
    result(0, 'old-stash\n'),
    result(),
    result(),
  ];
  const runCommand = (cmd, args) => {
    calls.push([cmd, args]);
    return responses.shift() ?? result();
  };

  assert.deepEqual(pushHeadToMain({ runCommand }), { ok: true });
  assert.equal(calls.some(([, args]) => args[0] === 'stash' && args[1] === 'apply'), false);
  assert.equal(calls.some(([, args]) => args[0] === 'stash' && args[1] === 'drop'), false);
});

test('restores and drops only the stash commit created by this invocation', () => {
  const calls = [];
  const responses = [
    result(0, 'old-stash\n'),
    result(0, 'Saved working directory\n'),
    result(0, 'new-stash\n'),
    result(),
    result(),
    result(),
    result(0, 'other-stash\tstash@{0}\nnew-stash\tstash@{1}\nold-stash\tstash@{2}\n'),
    result(),
  ];
  const runCommand = (cmd, args) => {
    calls.push([cmd, args]);
    return responses.shift() ?? result();
  };

  assert.deepEqual(pushHeadToMain({ runCommand }), { ok: true });
  assert.ok(calls.some(([, args]) => args.join(' ') === 'stash apply new-stash'));
  assert.ok(calls.some(([, args]) => args.join(' ') === 'stash drop stash@{1}'));
});
