/**
 * Invoke Cursor for PR-watch remediation: CLI agent, @cursor/sdk, or loop sentinel.
 */
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { WAKE_PATH, ensureWatchDir } from './pr-watch-state.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '../..');

const SENTINEL = 'AGENT_LOOP_WAKE_PR_WATCH';

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, {
    cwd: opts.cwd || REPO_ROOT,
    encoding: 'utf8',
    env: { ...process.env, ...(opts.env || {}) },
    timeout: opts.timeout || 0,
    shell: opts.shell ?? false,
    windowsHide: true,
  });
  return {
    ok: r.status === 0,
    status: r.status ?? 1,
    stdout: (r.stdout || '').trim(),
    stderr: (r.stderr || '').trim(),
    error: r.error,
  };
}

function commandExists(cmd) {
  const probe = process.platform === 'win32' ? 'where' : 'which';
  const r = spawnSync(probe, [cmd], { encoding: 'utf8', shell: true, windowsHide: true });
  return r.status === 0 && (r.stdout || '').trim().length > 0;
}

function defaultCursorBins() {
  const local = process.env.LOCALAPPDATA || '';
  const prog = process.env.ProgramFiles || 'C:\\Program Files';
  return [
    path.join(local, 'cursor-agent', 'agent.cmd'),
    path.join(local, 'cursor-agent', 'agent.exe'),
    path.join(prog, 'cursor', 'resources', 'app', 'bin', 'cursor.cmd'),
    path.join(local, 'Programs', 'cursor', 'resources', 'app', 'bin', 'cursor.cmd'),
  ];
}

/**
 * Resolve executable for Cursor agent CLI.
 * @returns {{ backend: string, cmd: string, argsPrefix: string[] }}
 */
export function resolveCursorInvoker() {
  if (process.env.AR_CURSOR_AGENT_CMD) {
    const parts = process.env.AR_CURSOR_AGENT_CMD.trim().split(/\s+/);
    return { backend: 'env', cmd: parts[0], argsPrefix: parts.slice(1) };
  }

  if (commandExists('agent')) {
    return { backend: 'cli-agent', cmd: 'agent', argsPrefix: [] };
  }

  for (const bin of defaultCursorBins()) {
    if (fs.existsSync(bin)) {
      if (bin.toLowerCase().includes('cursor')) {
        return { backend: 'cursor-bin', cmd: bin, argsPrefix: ['agent'] };
      }
      return { backend: 'cli-agent-path', cmd: bin, argsPrefix: [] };
    }
  }

  if (process.env.CURSOR_API_KEY) {
    return { backend: 'sdk', cmd: null, argsPrefix: [] };
  }

  return { backend: 'sentinel', cmd: null, argsPrefix: [] };
}

function buildPrompt({ prompt, prNumbers }) {
  const prList = prNumbers?.length ? prNumbers.join(', ') : '(see .ar-pr-watch/state.json)';
  return `${prompt}

Remediation PR(s) (oldest first): ${prList}
Repo: ${REPO_ROOT}
Do not bypass WORKFLOW.md: wait-for-bots, ## Feedback plan, in-thread closure, pr:bot-feedback-check before merge.
Pi verify: http://100.78.28.10/`;
}

async function invokeSdk(text, { timeoutMs }) {
  let Agent;
  try {
    ({ Agent } = await import('@cursor/sdk'));
  } catch (e) {
    return {
      ok: false,
      backend: 'sdk',
      detail: `@cursor/sdk not installed (${e.message}). Run: npm install @cursor/sdk`,
    };
  }
  const apiKey = process.env.CURSOR_API_KEY;
  if (!apiKey) {
    return { ok: false, backend: 'sdk', detail: 'CURSOR_API_KEY unset' };
  }
  const modelId = process.env.AR_CURSOR_AGENT_MODEL || 'composer-2.5';
  const agent = await Agent.create({
    apiKey,
    model: { id: modelId },
    local: { cwd: REPO_ROOT },
  });
  try {
    const run = await agent.send(text);
    const result = await Promise.race([
      run.wait(),
      new Promise((_, reject) => {
        setTimeout(() => reject(new Error(`SDK run timeout ${timeoutMs}ms`)), timeoutMs);
      }),
    ]);
    return {
      ok: result.status !== 'error',
      backend: 'sdk',
      detail: `run ${result.id} status=${result.status}`,
      result,
    };
  } finally {
    await agent[Symbol.asyncDispose]();
  }
}

function invokeCli(invoker, text, { force, timeoutMs }) {
  const args = [...invoker.argsPrefix];
  if (force) args.push('--force');
  args.push('-p', text);
  const r = run(invoker.cmd, args, { timeout: timeoutMs, shell: process.platform === 'win32' });
  if (r.error) {
    return { ok: false, backend: invoker.backend, detail: r.error.message };
  }
  return {
    ok: r.ok,
    backend: invoker.backend,
    detail: r.ok ? 'cli exit 0' : (r.stderr || r.stdout || `exit ${r.status}`).slice(0, 500),
    stdout: r.stdout,
    stderr: r.stderr,
  };
}

function invokeSentinel(text, prNumbers) {
  ensureWatchDir();
  const payload = {
    prompt: text,
    prNumbers,
    repoRoot: REPO_ROOT,
    at: new Date().toISOString(),
  };
  fs.writeFileSync(WAKE_PATH, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  const line = `${SENTINEL} ${JSON.stringify({ prompt: text, prNumbers })}`;
  console.log(line);
  return {
    ok: true,
    backend: 'sentinel',
    detail: `Wrote ${WAKE_PATH}; emit ${SENTINEL} for Cursor /loop monitor`,
    sentinel: line,
  };
}

/**
 * @param {{ prompt: string, prNumbers: number[], force?: boolean, timeoutMin?: number }}
 */
export async function invokeCursorForPrWatch({ prompt, prNumbers, force = true, timeoutMin = 90 }) {
  const invoker = resolveCursorInvoker();
  const text = buildPrompt({ prompt, prNumbers });
  const timeoutMs = Math.max(60_000, (timeoutMin || 90) * 60 * 1000);

  if (invoker.backend === 'sdk') {
    return invokeSdk(text, { timeoutMs });
  }
  if (invoker.backend === 'sentinel') {
    return invokeSentinel(text, prNumbers);
  }
  return invokeCli(invoker, text, { force, timeoutMs });
}

export function probeCursorInvoker() {
  const invoker = resolveCursorInvoker();
  const lines = [`backend=${invoker.backend}`];
  if (invoker.cmd) lines.push(`cmd=${invoker.cmd}`);
  if (invoker.argsPrefix?.length) lines.push(`argsPrefix=${invoker.argsPrefix.join(' ')}`);
  if (invoker.backend === 'sentinel') {
    lines.push('Install Cursor CLI: https://cursor.com/docs/cli/install');
    lines.push('Or set AR_CURSOR_AGENT_CMD / CURSOR_API_KEY + npm install @cursor/sdk');
  }
  return { invoker, lines };
}
