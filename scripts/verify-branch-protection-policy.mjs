import assert from 'node:assert/strict';
import { mergeCheckContexts } from './apply-branch-protection.mjs';

assert.deepEqual(mergeCheckContexts([
  'payload builder (pytest)', 'process liveness (Windows)',
  'bot-presence-gate', 'bot-feedback-gate', 'payload builder (pytest)',
]), ['payload builder (pytest)', 'process liveness (Windows)', 'bot-feedback-gate']);
assert.deepEqual(mergeCheckContexts([]), ['bot-feedback-gate']);
console.log('Branch protection reviewer policy regression passed');
