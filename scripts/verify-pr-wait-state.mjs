import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { writeBotWaitStateFile, readBotWaitStateFile, botWaitStatePath } from './lib/bot-wait-state.mjs';
const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'wait-state-cas-'));
const previousStateDir = process.env.AR_BOT_WAIT_STATE_DIR;
try {
  process.env.AR_BOT_WAIT_STATE_DIR = path.join(temporaryRoot, 'state');
  writeBotWaitStateFile(123, { anchor: '2026-10-11T00:00:00Z', requiredKeys: ['sourcery'] }, temporaryRoot);
  const filename = botWaitStatePath(123, temporaryRoot);
  const accepted = fs.readFileSync(filename, 'utf8');
  const originalRename = fs.renameSync;
  try {
    fs.renameSync = () => { throw new Error('replacement interrupted'); };
    const attempt = readBotWaitStateFile(123, temporaryRoot);
    attempt.anchor = '2026-10-11T00:01:00Z';
    assert.throws(() => writeBotWaitStateFile(123, attempt, temporaryRoot), /replacement interrupted/);
  } finally {
    fs.renameSync = originalRename;
  }
  assert.equal(fs.readFileSync(filename, 'utf8'), accepted);
  const older = readBotWaitStateFile(123, temporaryRoot);
  const newer = readBotWaitStateFile(123, temporaryRoot);
  Object.assign(newer, { anchor: '2026-10-11T01:00:00Z', readyAt: null });
  writeBotWaitStateFile(123, newer, temporaryRoot);
  assert.throws(() => writeBotWaitStateFile(123, older, temporaryRoot), /changed since read/);
  assert.equal(readBotWaitStateFile(123, temporaryRoot).anchor, newer.anchor);
  const lock = `${filename}.lock`;
  fs.writeFileSync(lock, 'another writer');
  try {
    assert.throws(() => writeBotWaitStateFile(123, newer, temporaryRoot), /update is locked/);
  } finally {
    fs.unlinkSync(lock);
  }
  assert.deepEqual(fs.readdirSync(path.dirname(filename)), ['123.json']);
} finally {
  if (previousStateDir === undefined) delete process.env.AR_BOT_WAIT_STATE_DIR;
  else process.env.AR_BOT_WAIT_STATE_DIR = previousStateDir;
  fs.rmSync(temporaryRoot, { recursive: true, force: true });
}
console.log('Wait-state CAS, occupied-lock and interrupted-replacement regressions passed');
