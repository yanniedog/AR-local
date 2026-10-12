/** Execute the actual workflow guard bodies: missing verification must be red. */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

const workflow = readFileSync(new URL('../.github/workflows/pi-deploy-watchdog.yml', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
function stepBody(name) {
  const step = workflow.split('      - name: ').find((part) => part.startsWith(name + '\n'));
  assert.ok(step, 'Missing guard step: ' + name);
  const body = step.split('        run: |\n')[1];
  assert.ok(body, 'Missing guard body');
  return body.split('\n').map((line) => line.replace(/^          /, '')).join('\n');
}
let bash = 'bash';
if (process.platform === 'win32') {
  const git = spawnSync('git', ['--exec-path'], { encoding: 'utf8' });
  assert.equal(git.status, 0);
  bash = path.resolve(git.stdout.trim(), '../../..', 'bin/bash.exe');
}
const directory = mkdtempSync(path.join(tmpdir(), 'ar-watchdog-guard-'));
try {
  const summary = path.join(directory, 'summary.md');
  const run = (name, values = {}) => spawnSync(bash, ['--noprofile', '--norc', '-c', stepBody(name)], {
    encoding: 'utf8', timeout: 10_000,
    env: { ...process.env, GITHUB_STEP_SUMMARY: summary.replaceAll('\\', '/'), ...values },
  });
  for (const name of ['Fail verification (Pi SSH not configured)',
    'Fail verification (Tailscale OAuth missing for hosted runner)']) {
    const result = run(name);
    assert.equal(result.status, 1, result.error?.message || result.stderr);
    assert.match(result.stdout, /::error::Pi deployment was not verified/);
    assert.match(readFileSync(summary, 'utf8'), /not verified/);
  }
  for (const exit of ['1', '2', '', 'unknown']) {
    assert.equal(run('Fail on drift or unhealthy runtime', { VERIFY_EXIT: exit }).status, 1);
  }
  assert.equal(run('Fail on drift or unhealthy runtime', { VERIFY_EXIT: '0' }).status, 0);
  assert.doesNotMatch(workflow, /pi_deploy_verify\.py --deploy|systemctl (start|restart|enable)/);
  console.log('Pi watchdog guards: missing configuration and failed verification fail; verified result passes');
} finally {
  const target = path.resolve(directory);
  assert.ok(target.startsWith(path.resolve(tmpdir()) + path.sep) && path.basename(target).startsWith('ar-watchdog-guard-'));
  rmSync(target, { recursive: true, force: true });
}
