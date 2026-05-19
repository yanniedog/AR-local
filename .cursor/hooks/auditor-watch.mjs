#!/usr/bin/env node
/**
 * Post-stop hook: quick agent auditor scan, then chief/orchestrator chain.
 * Chain: auditor → chief → orchestrator (via chief delegation).
 */
import { execFileSync, execSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';

const repoRoot = process.cwd();
const EXEC_TIMEOUT_MS = 8000;
/** Full scan runs chief:scan + ship:closeout; 7s was too short on Windows. */
const AUDITOR_SCAN_TIMEOUT_MS = 45000;

function run(cmd, timeoutMs = EXEC_TIMEOUT_MS) {
  try {
    return execSync(cmd, {
      cwd: repoRoot,
      encoding: 'utf8',
      stdio: ['pipe', 'pipe', 'pipe'],
      timeout: timeoutMs,
      maxBuffer: 2 * 1024 * 1024,
    }).trim();
  } catch (error) {
    const stdout = (error.stdout || '').toString().trim();
    if (stdout) return stdout;
    return '';
  }
}

function resolveAuditorScanScript() {
  const repoScript = join(repoRoot, 'scripts', 'agent-auditor-scan.mjs');
  const wf = process.env.CURSOR_WORKFLOW_SCRIPTS;
  if (wf) {
    const globalScript = join(wf, 'agent-auditor-scan.mjs');
    if (existsSync(globalScript)) return globalScript;
  }
  return repoScript;
}

function githubRepoSlug() {
  try {
    const url = run('git config --get remote.origin.url', 2000);
    const match = url.match(/github\.com[:/]([^/]+\/[^/.]+)/);
    return match ? match[1].replace(/\.git$/, '') : '';
  } catch {
    return '';
  }
}

function quickAuditorScan() {
  const script = resolveAuditorScanScript();
  if (!existsSync(script)) {
    return {
      exitCode: 2,
      findings: [
        {
          severity: 'fail',
          message: `agent-auditor-scan not found: ${script}`,
        },
      ],
    };
  }

  const args = [script, '--hook', '--since-minutes', '45', '--no-write'];
  let stdout = '';
  let stderr = '';
  let status = 0;

  try {
    stdout = execFileSync(process.execPath, args, {
      cwd: repoRoot,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
      timeout: AUDITOR_SCAN_TIMEOUT_MS,
      maxBuffer: 2 * 1024 * 1024,
    }).trim();
  } catch (error) {
    stdout = (error.stdout || '').toString().trim();
    stderr = (error.stderr || '').toString().trim();
    status = error.status ?? 2;
  }

  if (!stdout) {
    const detail = stderr ? stderr.slice(0, 240) : `exit ${status}, script ${script}`;
    return {
      exitCode: 1,
      findings: [
        {
          severity: 'warn',
          message: `agent-auditor-scan produced no output in hook (${detail})`,
        },
      ],
    };
  }

  try {
    const report = JSON.parse(stdout);
    return {
      exitCode: report.exitCode ?? status ?? 0,
      findings: report.findings ?? [],
    };
  } catch {
    return {
      exitCode: 1,
      findings: [
        {
          severity: 'warn',
          message: `agent-auditor-scan returned non-JSON in hook: ${stdout.slice(0, 160)}`,
        },
      ],
    };
  }
}

function main() {
  let dirty = false;
  let openPrCount = 0;
  try {
    dirty = Boolean(run('git status --porcelain', 2000));
  } catch {
    /* */
  }
  try {
    const slug = githubRepoSlug();
    const repoFlag = slug ? ` --repo ${slug}` : '';
    const parsed = JSON.parse(run(`gh pr list --state open --json number${repoFlag}`, 4000) || '[]');
    openPrCount = Array.isArray(parsed) ? parsed.length : 0;
  } catch {
    /* */
  }

  const audit = quickAuditorScan();
  const parts = [];

  if (audit.exitCode >= 2) {
    const top = audit.findings
      .filter((f) => f.severity === 'fail')
      .slice(0, 3)
      .map((f) => f.message)
      .join('; ');
    parts.push(
      `Agent auditor: CRITICAL (${top || 'see npm run agent:auditor'}). ` +
        'Run agent auditor per .cursor/skills/agent-auditor/SKILL.md, then chief remediation.',
    );
  } else if (audit.exitCode === 1 && audit.findings.length) {
    const top = audit.findings.slice(0, 2).map((f) => f.message).join('; ');
    parts.push(`Agent auditor: warnings (${top}). Consider "run agent auditor".`);
  }

  if (dirty || openPrCount > 0) {
    const signals = [];
    if (dirty) signals.push('uncommitted changes');
    if (openPrCount > 0) signals.push(`${openPrCount} open PR(s)`);
    parts.push(
      `Chief agent: ${signals.join(' and ')} detected. ` +
        'Run one coordination cycle per .cursor/skills/chief-agent/SKILL.md. ' +
        'Chief accepts auditor recommendations this cycle; delegates ship bar to workflow-orchestrator.',
    );
  }

  if (!parts.length) {
    console.log('{}');
    return;
  }
  console.log(JSON.stringify({ followup_message: parts.join(' ') }));
}

main();
