import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { writeBotWaitStateFile, readBotWaitStateFile, botWaitStatePath } from './lib/bot-wait-state.mjs';

const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'wait-state-cas-'));
const previousStateDir = process.env.AR_BOT_WAIT_STATE_DIR;
const python = process.platform === 'win32' ? 'python' : 'python3';
const helper = fileURLToPath(new URL('./lib/bot-wait-state-write.py', import.meta.url));
const moduleUrl = new URL('./lib/bot-wait-state.mjs', import.meta.url).href;
const children = new Set();
const pythonImport = `
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('wait_state', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
destination = Path(sys.argv[2])
`;

function startChild(command, args) {
  const child = spawn(command, args, { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  children.add(child);
  let stdout = '';
  let stderr = '';
  let readyResolve;
  let readyReject;
  const ready = new Promise((resolve, reject) => { readyResolve = resolve; readyReject = reject; });
  const timer = setTimeout(() => readyReject(new Error(`Child did not become ready: ${stderr}`)), 10_000);
  child.stdout.on('data', (part) => {
    stdout += part;
    if (/READY\r?\n/.test(stdout)) { clearTimeout(timer); readyResolve(); }
  });
  child.stderr.on('data', (part) => { stderr += part; });
  const closed = new Promise((resolve, reject) => {
    child.once('error', (error) => { clearTimeout(timer); readyReject(error); reject(error); });
    child.once('close', (code, signal) => {
      clearTimeout(timer);
      children.delete(child);
      if (!/READY\r?\n/.test(stdout)) readyReject(new Error(`Child exited before ready: ${stderr}`));
      resolve({ code, signal, stdout, stderr });
    });
  });
  return { child, ready, closed };
}

function pythonChild(source, filename) {
  return startChild(python, ['-I', '-S', '-B', '-u', '-c', pythonImport + source, helper, filename]);
}

function runPython(source, filename) {
  return spawnSync(python, ['-I', '-S', '-B', '-c', pythonImport + source, helper, filename], {
    encoding: 'utf8', windowsHide: true, timeout: 10_000, killSignal: 'SIGKILL', maxBuffer: 64 * 1024,
  });
}

try {
  process.env.AR_BOT_WAIT_STATE_DIR = path.join(temporaryRoot, 'state');
  writeBotWaitStateFile(123, { anchor: '2026-10-11T00:00:00Z', requiredKeys: ['sourcery'] }, temporaryRoot);
  const filename = botWaitStatePath(123, temporaryRoot);
  const lock = `${filename}.lock`;
  const sidecar = `${filename}.writer-lock`;
  const accepted = fs.readFileSync(filename, 'utf8');

  const interrupted = runPython(`
def interrupted_replace(*args):
    raise RuntimeError('replacement interrupted')
module.os.replace = interrupted_replace
module.write_state(destination, b'{"anchor":"interrupted"}\\n', module.current_fingerprint(destination))
`, filename);
  assert.equal(interrupted.status, 1);
  assert.match(interrupted.stderr, /replacement interrupted/);
  assert.equal(fs.readFileSync(filename, 'utf8'), accepted);

  const older = readBotWaitStateFile(123, temporaryRoot);
  const newer = readBotWaitStateFile(123, temporaryRoot);
  Object.assign(newer, { anchor: '2026-10-11T01:00:00Z', readyAt: null });
  writeBotWaitStateFile(123, newer, temporaryRoot);
  assert.throws(() => writeBotWaitStateFile(123, older, temporaryRoot), /changed since read/);
  assert.equal(readBotWaitStateFile(123, temporaryRoot).anchor, newer.anchor);

  // Neither empty nor PID-shaped legacy locks prove the old writer is dead.
  for (const legacyContents of ['', JSON.stringify({ pid: process.pid }), 'another writer']) {
    const descriptor = fs.openSync(lock, 'wx');
    try {
      fs.writeFileSync(descriptor, legacyContents);
      assert.throws(() => writeBotWaitStateFile(123, newer, temporaryRoot), /update is locked.*legacy/);
      assert.equal(fs.readFileSync(lock, 'utf8'), legacyContents);
      assert.equal(readBotWaitStateFile(123, temporaryRoot).anchor, newer.anchor);
    } finally {
      fs.closeSync(descriptor);
      fs.unlinkSync(lock);
    }
  }

  const holder = pythonChild(`
with module.state_write_lock(destination):
    print('READY', flush=True)
    sys.stdin.readline()
`, filename);
  await holder.ready;
  assert.throws(() => writeBotWaitStateFile(123, newer, temporaryRoot), /update is locked/);
  assert.throws(() => fs.openSync(lock, 'wx'), { code: 'EEXIST' }); // Old writer excluded.
  assert.equal(fs.statSync(lock, { bigint: true }).ino, fs.statSync(sidecar, { bigint: true }).ino);
  // Node uses TerminateProcess on Windows. Only this owned child is terminated;
  // no process-existence probe, signal zero, console event, or PID takeover.
  holder.child.kill('SIGKILL');
  await holder.closed;
  assert.equal(fs.existsSync(lock), true, 'abrupt exit must leave the recovery alias');
  writeBotWaitStateFile(123, newer, temporaryRoot);
  assert.equal(fs.existsSync(lock), false, 'next writer retires its own abandoned alias');
  assert.equal(fs.existsSync(sidecar), true, 'persistent kernel sidecar must never be removed');

  // A crash after replace has an ambiguous caller outcome, but recovery must
  // retain the committed state and still reject a stale pre-crash snapshot.
  const afterReplace = pythonChild(`
def pause_after_replace(directory):
    print('READY', flush=True)
    sys.stdin.readline()
module.sync_directory = pause_after_replace
module.write_state(destination, b'{"anchor":"committed-before-crash"}\\n', module.current_fingerprint(destination))
`, filename);
  await afterReplace.ready;
  afterReplace.child.kill('SIGKILL');
  await afterReplace.closed;
  assert.throws(() => writeBotWaitStateFile(123, newer, temporaryRoot), /changed since read/);
  assert.equal(readBotWaitStateFile(123, temporaryRoot).anchor, 'committed-before-crash');
  assert.equal(fs.existsSync(lock), false);

  const replacedAlias = runPython(`
with module.state_write_lock(destination):
    legacy = Path(str(destination) + '.lock')
    legacy.unlink()
    legacy.write_text('foreign replacement')
`, filename);
  assert.equal(replacedAlias.status, 1);
  assert.match(replacedAlias.stderr, /lock identity changed/);
  assert.equal(fs.readFileSync(lock, 'utf8'), 'foreign replacement', 'cleanup must not delete a foreign lock');
  fs.unlinkSync(lock);

  const writerSource = `
const { readJsonState, writeJsonAtomically } = await import(process.argv[1]);
const state = readJsonState(process.argv[2]);
state.anchor = process.argv[3];
console.log('READY');
process.stdin.once('data', () => {
  try { writeJsonAtomically(process.argv[2], state); console.log(JSON.stringify({ ok: true, anchor: state.anchor })); }
  catch (error) { console.log(JSON.stringify({ ok: false, error: error.message })); }
  process.stdin.destroy();
});
`;
  const writers = ['writer-a', 'writer-b'].map((tag) => startChild(process.execPath,
    ['--input-type=module', '-e', writerSource, moduleUrl, filename, tag]));
  await Promise.all(writers.map((writer) => writer.ready));
  writers.forEach((writer) => writer.child.stdin.end('write'));
  const results = await Promise.all(writers.map((writer) => writer.closed));
  results.forEach((result) => assert.equal(result.code, 0, result.stderr));
  const outcomes = results.map((result) => JSON.parse(result.stdout.trim().split('\n').at(-1)));
  assert.equal(outcomes.filter((result) => result.ok).length, 1, 'exactly one stale-snapshot writer wins');
  assert.match(outcomes.find((result) => !result.ok).error, /changed since read|update is locked/);
  assert.equal(readBotWaitStateFile(123, temporaryRoot).anchor, outcomes.find((result) => result.ok).anchor);
  writeBotWaitStateFile(123, readBotWaitStateFile(123, temporaryRoot), temporaryRoot);
  if (process.platform !== 'win32') {
    const directorySync = runPython(`
import errno, json, stat
original_fsync = module.os.fsync
directory_synced = False
def record_fsync(descriptor):
    global directory_synced
    directory_synced = directory_synced or stat.S_ISDIR(module.os.fstat(descriptor).st_mode)
    original_fsync(descriptor)
module.os.fsync = record_fsync
module.write_state(destination, b'{"anchor":"directory-synced"}\\n', module.current_fingerprint(destination))
assert directory_synced, 'accepted replace must sync its directory'
for code in (errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EIO):
    def failing_fsync(descriptor):
        if stat.S_ISDIR(module.os.fstat(descriptor).st_mode):
            raise OSError(code, 'injected directory fsync failure')
        original_fsync(descriptor)
    module.os.fsync = failing_fsync
    content = json.dumps({'anchor': str(code)}).encode('utf-8')
    try:
        module.write_state(destination, content, module.current_fingerprint(destination))
        assert code != errno.EIO, 'genuine I/O failure must propagate'
    except RuntimeError as error:
        assert code == errno.EIO and 'was replaced' in str(error)
    assert json.loads(destination.read_text())['anchor'] == str(code)
`, filename);
    assert.equal(directorySync.status, 0, directorySync.stderr);
    assert.equal(directorySync.stderr.split('does not support directory fsync').length - 1, 3);
  }
  assert.deepEqual(fs.readdirSync(path.dirname(filename)).sort(), ['123.json', '123.json.writer-lock']);
} finally {
  // These are only children spawned above, never unrelated console processes.
  await Promise.all([...children].map((child) => new Promise((resolve) => {
    child.once('close', resolve);
    child.kill('SIGKILL');
  })));
  if (previousStateDir === undefined) delete process.env.AR_BOT_WAIT_STATE_DIR;
  else process.env.AR_BOT_WAIT_STATE_DIR = previousStateDir;
  fs.rmSync(temporaryRoot, { recursive: true, force: true });
}
console.log('Wait-state CAS, legacy exclusion, concurrent writers and child-crash recovery regressions passed');
