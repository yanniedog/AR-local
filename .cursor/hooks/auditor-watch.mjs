#!/usr/bin/env node
/**
 * Post-stop hook: quick agent auditor scan, then chief/orchestrator chain.
 * Chain: auditor → chief → orchestrator (via chief delegation).
 */
import { execSync } from 'node:child_process';
import { join } from 'node:path';

const repoRoot = process.cwd();
const EXEC_TIMEOUT_MS = 8000;
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
    if (error?.code === 'ETIMEDOUT' || error?.signal === 'SIGTERM') return '';
    return '';
  }
}

function auditorScanScript() {
  const wf = process.env.CURSOR_WORKFLOW_SCRIPTS;
  if (wf) return join(wf, 'agent-auditor-scan.mjs');
  return join(repoRoot, 'scripts', 'agent-auditor-scan.mjs');
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
  const script = auditorScanScript();
  try {
    const out = run(`node "${script}" --hook --since-minutes 45 --no-write`, 7000);
    if (!out) return { exitCode: 0, findings: [] };
    const report = JSON.parse(out);
    return { exitCode: report.exitCode ?? 0, findings: report.findings ?? [] };
  } catch {
    return { exitCode: 0, findings: [] };
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
