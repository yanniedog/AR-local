/**
 * Shared agent-auditor scan logic (transcripts, git, chief:scan).
 */
import { execSync } from 'node:child_process';
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  statSync,
  appendFileSync,
  writeFileSync,
  openSync,
  readSync,
  closeSync,
} from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import {
  classifyThreads,
  fetchPullRequestThreads,
  hasGh,
  repoSlug,
} from './gh-pr-review-threads.mjs';

const BUCK_PASS_PHRASES = [
  /\byou should run\b/i,
  /\bhanding off the pr\b/i,
  /\bhanding off\b/i,
  /\bmerge[- ]ready\b/i,
  /\bci green so we(?:'re| are) good\b/i,
  /\bno actionable feedback\b/i,
  /\buser can run\b/i,
  /\bask the user to run\b/i,
];

const OPEN_LOOP_PHRASES = [
  /\bmay need follow[- ]up\b/i,
  /\bdeferred\b/i,
  /\bleft for next cycle\b/i,
  /\bhandoff\b/i,
  /\bparent should\b/i,
  /\borchestrator not delegated\b/i,
  /\bpaused until remediation\b/i,
  /\bwithout naming an active\b/i,
];

const EARLY_DONE_PHRASES = [/\b(shipped|task done|all done)\b/i, /\bpr opened\b/i];

const ORCHESTRATOR_MARKERS = [
  /workflow-orchestrator/i,
  /workflow orchestrator/i,
  /SCAN→PLAN→DELEGATE/i,
];

const VERIFY_MARKERS = [/verify:local/i, /npm run verify/i];

export function sh(cmd, cwd, timeoutMs = 8000) {
  try {
    return execSync(cmd, {
      cwd,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
      timeout: timeoutMs,
      maxBuffer: 4 * 1024 * 1024,
    }).trim();
  } catch (e) {
    const out = (e.stdout || e.stderr || '').trim();
    if (e.status != null) return { error: true, status: e.status, out };
    return { error: true, out };
  }
}

export function repoRoot() {
  const r = sh('git rev-parse --show-toplevel', process.cwd());
  return typeof r === 'string' && r ? r : process.cwd();
}

export function projectSlugFromRoot(root) {
  const norm = root.replace(/\\/g, '/').replace(/:/g, '-').replace(/^\/+/, '');
  return norm.toLowerCase();
}

export function discoverTranscriptRoot(repoRootPath) {
  if (process.env.CURSOR_PROJECT_DIR) {
    const p = join(process.env.CURSOR_PROJECT_DIR, 'agent-transcripts');
    if (existsSync(p)) return p;
  }
  const slug = projectSlugFromRoot(repoRootPath);
  const p = join(homedir(), '.cursor', 'projects', slug, 'agent-transcripts');
  if (existsSync(p)) return p;
  return null;
}

export function listRecentTranscripts(transcriptRoot, sinceMinutes = 60) {
  if (!transcriptRoot) return [];
  const cutoff = Date.now() - sinceMinutes * 60 * 1000;
  const out = [];

  const addFile = (full, id, kind) => {
    let mtimeMs;
    try {
      mtimeMs = statSync(full).mtimeMs;
    } catch {
      return;
    }
    if (mtimeMs < cutoff) return;
    out.push({ id, path: full, mtimeMs, kind });
  };

  const walkSubagents = (subDir) => {
    let entries;
    try {
      entries = readdirSync(subDir);
    } catch {
      return;
    }
    for (const file of entries) {
      if (!file.endsWith('.jsonl')) continue;
      addFile(join(subDir, file), file.replace(/\.jsonl$/, ''), 'subagent');
    }
  };

  try {
    for (const ent of readdirSync(transcriptRoot, { withFileTypes: true })) {
      if (!ent.isDirectory()) continue;
      const parentDir = join(transcriptRoot, ent.name);
      addFile(join(parentDir, `${ent.name}.jsonl`), ent.name, 'parent');
      walkSubagents(join(parentDir, 'subagents'));
    }
  } catch {
    /* missing */
  }
  return out.sort((a, b) => b.mtimeMs - a.mtimeMs);
}

function readTranscriptTailLines(filePath, tailLines) {
  const CHUNK_BYTES = 256 * 1024;
  let fd;
  try {
    const size = statSync(filePath).size;
    if (size === 0) return { tail: [], lineCount: 0 };
    const readLen = Math.min(size, CHUNK_BYTES);
    const start = size - readLen;
    fd = openSync(filePath, 'r');
    const buf = Buffer.alloc(readLen);
    readSync(fd, buf, 0, readLen, start);
    closeSync(fd);
    const allLines = buf.toString('utf8').split(/\r?\n/).filter(Boolean);
    return { tail: allLines.slice(-tailLines), lineCount: allLines.length };
  } catch {
    if (fd != null) {
      try {
        closeSync(fd);
      } catch {
        /* */
      }
    }
    return { tail: [], lineCount: 0 };
  }
}

export function parseTranscriptFile(filePath, tailLines = 120) {
  let lines;
  let lineCount = 0;
  try {
    const st = statSync(filePath);
    if (st.size <= 512 * 1024) {
      const raw = readFileSync(filePath, 'utf8');
      const allLines = raw.split(/\r?\n/).filter(Boolean);
      lineCount = allLines.length;
      lines = allLines.slice(-tailLines);
    } else {
      const tailed = readTranscriptTailLines(filePath, tailLines);
      lines = tailed.tail;
      lineCount = tailed.lineCount;
    }
  } catch {
    return { lines: [], text: '', toolUses: 0, assistantTurns: 0, lineCount: 0 };
  }
  const text = lines.join('\n');
  let toolUses = 0;
  let assistantTurns = 0;
  for (const line of lines) {
    try {
      const row = JSON.parse(line);
      if (row.role === 'assistant') {
        assistantTurns++;
        for (const p of row.message?.content || []) {
          if (p.type === 'tool_use') toolUses++;
        }
      }
    } catch {
      /* skip */
    }
  }
  return { lines, text, toolUses, assistantTurns, lineCount };
}

export function extractMentions(text) {
  const branches = new Set();
  const prs = new Set();
  const paths = new Set();
  for (const m of text.matchAll(/\bagent\/[a-z0-9][\w-]*/gi)) branches.add(m[0]);
  for (const m of text.matchAll(/\bPR\s*#?(\d+)\b/gi)) prs.add(Number(m[1]));
  for (const m of text.matchAll(/\bgh pr view\s+(\d+)/gi)) prs.add(Number(m[1]));
  for (const m of text.matchAll(
    /(?:^|[\s"'`])([/\\]?(?:[\w.-]+[/\\])*[\w.-]+\.(?:py|mjs|js|mdc|md|json))\b/g,
  )) {
    const p = m[1].replace(/\\/g, '/');
    if (!p.includes('node_modules')) paths.add(p);
  }
  return { branches: [...branches], prs: [...prs], paths: [...paths].slice(0, 40) };
}

export function runChiefScan(repoRootPath, timeoutMs = 12000) {
  const r = sh('npm run chief:scan', repoRootPath, timeoutMs);
  if (typeof r === 'object' && r.error) {
    return { exitCode: r.status ?? 1, output: r.out || '' };
  }
  return { exitCode: 0, output: r };
}

export function gitSignals(repoRootPath) {
  const porcelain = sh('git status --porcelain', repoRootPath, 4000);
  const branch = sh('git branch --show-current', repoRootPath, 4000);
  const dirty = Boolean(porcelain && typeof porcelain === 'string' && porcelain.length > 0);
  let openPrs = [];
  const gh = sh('gh pr list --state open --json number,title,headRefName', repoRootPath, 6000);
  if (typeof gh === 'string' && gh.startsWith('[')) {
    try {
      openPrs = JSON.parse(gh);
    } catch {
      openPrs = [];
    }
  }
  return {
    dirty,
    branch: typeof branch === 'string' ? branch : '',
    openPrs,
    porcelainLines:
      typeof porcelain === 'string' ? porcelain.split(/\r?\n/).filter(Boolean) : [],
  };
}

export function runAudit(opts) {
  const { repoRoot: root = repoRoot(), sinceMinutes = 60, hook = false } = opts;
  const transcriptRoot = discoverTranscriptRoot(root);
  const transcripts = listRecentTranscripts(transcriptRoot, sinceMinutes);
  const git = gitSignals(root);
  const chief = runChiefScan(root, hook ? 6000 : 12000);
  const findings = [];

  const add = (dimension, severity, message, skillPatch, transcriptId) => {
    findings.push({
      dimension,
      severity,
      message,
      skillPatch: skillPatch || null,
      transcriptId: transcriptId || null,
    });
  };

  const orchestratorHits = [];
  const branchMentions = new Map();
  const pathMentions = new Map();
  const parsedByTranscript = new Map();

  for (const t of transcripts) {
    const parsed = parseTranscriptFile(t.path, hook ? 60 : 120);
    parsedByTranscript.set(t.id, parsed);
    const { text, toolUses, assistantTurns } = parsed;
    const mentions = extractMentions(text);

    for (const b of mentions.branches) {
      if (!branchMentions.has(b)) branchMentions.set(b, new Set());
      branchMentions.get(b).add(t.id);
    }
    for (const p of mentions.paths) {
      if (!pathMentions.has(p)) pathMentions.set(p, new Set());
      pathMentions.get(p).add(t.id);
    }

    if (assistantTurns > 0 && toolUses === 0) {
      add(
        'execution',
        'warn',
        `Prompt-only subagent (no tool calls): ${t.id.slice(0, 8)}…`,
        'chief-agent / workflow-orchestrator',
        t.id,
      );
    }

    if (
      toolUses === 0 &&
      parsed.lineCount <= 4 &&
      Date.now() - t.mtimeMs < sinceMinutes * 60 * 1000 &&
      t.kind === 'subagent'
    ) {
      add(
        'execution',
        'warn',
        `Stalled subagent transcript: ${t.id.slice(0, 8)}…`,
        'chief-agent',
        t.id,
      );
    }

    for (const re of BUCK_PASS_PHRASES) {
      if (re.test(text)) {
        add(
          'accountability',
          'warn',
          `Buck-passing phrasing in ${t.id.slice(0, 8)}…`,
          'chief-agent',
          t.id,
        );
        break;
      }
    }

    if (git.openPrs.length > 0) {
      for (const re of EARLY_DONE_PHRASES) {
        if (re.test(text)) {
          add(
            'ship_bar',
            'fail',
            `Early completion language with open PR(s): ${t.id.slice(0, 8)}…`,
            'workflow-orchestrator / no-early-stop-after-pr',
            t.id,
          );
          break;
        }
      }
    }

    if (ORCHESTRATOR_MARKERS.some((re) => re.test(text))) {
      orchestratorHits.push({ id: t.id, mtimeMs: t.mtimeMs });
    }

    const claimedMerge = /\b(merged|squash merge|pr merge)\b/i.test(text);
    const ranVerify = VERIFY_MARKERS.some((re) => re.test(text));
    if (claimedMerge && !ranVerify && !hook) {
      add(
        'verification',
        'warn',
        `Merge language without verify:local in ${t.id.slice(0, 8)}…`,
        'every-chat-commit-verify-local',
        t.id,
      );
    }

    const branchInText = mentions.branches[0];
    const checkoutMatch = text.match(/git checkout\s+(\S+)/);
    if (branchInText && checkoutMatch && checkoutMatch[1] !== branchInText) {
      add(
        'git_hygiene',
        'fail',
        `Branch mention (${branchInText}) vs checkout (${checkoutMatch[1]}) in ${t.id.slice(0, 8)}…`,
        'chief-agent',
        t.id,
      );
    }
  }

  orchestratorHits.sort((a, b) => b.mtimeMs - a.mtimeMs);
  const fiveMinMs = 5 * 60 * 1000;
  for (let i = 0; i < orchestratorHits.length; i++) {
    for (let j = i + 1; j < orchestratorHits.length; j++) {
      const gap = orchestratorHits[i].mtimeMs - orchestratorHits[j].mtimeMs;
      if (gap > fiveMinMs) break;
      add(
        'dedupe',
        'warn',
        `Duplicate orchestrator within 5m: ${orchestratorHits[j].id.slice(0, 8)}… / ${orchestratorHits[i].id.slice(0, 8)}…`,
        'chief-agent',
        orchestratorHits[i].id,
      );
    }
  }

  for (const [path, ids] of pathMentions) {
    if (ids.size > 1) {
      add(
        'concurrency',
        'warn',
        `Overlapping path (${path}) across ${[...ids].map((x) => x.slice(0, 8)).join(', ')}`,
        'chief-agent',
        null,
      );
    }
  }
  for (const [branch, ids] of branchMentions) {
    if (ids.size > 1) {
      add(
        'concurrency',
        'warn',
        `Same branch (${branch}) in multiple transcripts`,
        'chief-agent',
        null,
      );
    }
  }

  if (chief.exitCode === 1) {
    const recentChiefSpawn = transcripts.some((t) => {
      const text = parsedByTranscript.get(t.id)?.text ?? '';
      return /chief-agent|chief:scan|run chief/i.test(text);
    });
    if (!recentChiefSpawn) {
      add(
        'chief_coordination',
        'fail',
        'chief:scan exit 1 with no recent chief remediation transcript',
        'chief-agent',
        null,
      );
    } else {
      add('chief_coordination', 'warn', 'chief:scan exit 1 — confirm remediation active', 'chief-agent', null);
    }
  }

  if (git.dirty && git.branch === 'main') {
    add('git_hygiene', 'fail', 'Dirty main branch', 'chief-agent / chief:scan', null);
  }

  if (git.openPrs.length > 0) {
    const shipCloseout = sh('npm run ship:closeout:strict', root, hook ? 8000 : 15000);
    if (typeof shipCloseout === 'object' && shipCloseout.error && shipCloseout.status === 2) {
      add(
        'ship_bar',
        'warn',
        `ship:closeout:strict exit 2 with open PR(s) #${git.openPrs.map((p) => p.number).join(', #')}`,
        'workflow-orchestrator',
        null,
      );
    }
  }

  const chiefReport = transcripts.find((t) => t.kind === 'parent');
  if (chiefReport) {
    const chiefText = parsedByTranscript.get(chiefReport.id)?.text ?? '';
    for (const re of OPEN_LOOP_PHRASES) {
      if (re.test(chiefText)) {
        const hasWorkerId = /\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b/i.test(
          chiefText,
        );
        if (!hasWorkerId) {
          add(
            'open_loops',
            'fail',
            `Handoff/defer language in chief report without active worker ID (${chiefReport.id.slice(0, 8)}…)`,
            'chief-agent / close-loop-never-defer',
            chiefReport.id,
          );
          break;
        }
      }
    }
  }

  if (!hook && git.branch === 'main') {
    const loopCheck = sh('npm run close-loop:check -- --post-merge-gap', root, hook ? 12000 : 20000);
    if (typeof loopCheck === 'object' && loopCheck.error && loopCheck.status === 1) {
      add(
        'open_loops',
        'fail',
        'Post-merge gap detected (close-loop:check exit 1)',
        'close-loop-never-defer / workflow-orchestrator',
        null,
      );
    }
  }

  if (!hook && hasGh()) {
    try {
      const raw = sh('gh pr list --state closed --limit 10 --json number,title,merged', root, 12000);
      if (typeof raw === 'string' && raw) {
        const closedUnmerged = JSON.parse(raw).filter((p) => !p.merged);
        if (closedUnmerged.length) {
          const { owner, name } = repoSlug();
          for (const row of closedUnmerged.slice(0, 5)) {
            const pr = fetchPullRequestThreads(owner, name, row.number);
            const violations = classifyThreads(pr.threads);
            if (violations.length) {
              add(
                'open_loops',
                'fail',
                `Closed unmerged PR #${row.number} has ${violations.length} open bot thread(s) — agents must not close without merge unless waived`,
                'workflow-orchestrator / pr-review-bot-replies',
                null,
              );
            }
          }
        }
      }
    } catch {
      /* gh unavailable or repo not authenticated */
    }
  }

  const scores = scoreDimensions(findings);
  const maxSeverity = findings.reduce(
    (m, f) => (severityRank(f.severity) > severityRank(m) ? f.severity : m),
    'pass',
  );
  const exitCode = maxSeverity === 'fail' ? 2 : maxSeverity === 'warn' ? 1 : 0;

  return {
    repoRoot: root,
    transcriptRoot,
    sinceMinutes,
    scannedTranscripts: transcripts.length,
    git,
    chiefExitCode: chief.exitCode,
    findings,
    scores,
    exitCode,
    generatedAt: new Date().toISOString(),
  };
}

function severityRank(s) {
  if (s === 'fail') return 3;
  if (s === 'warn') return 2;
  return 1;
}

function scoreDimensions(findings) {
  const dims = [
    'accountability',
    'open_loops',
    'ship_bar',
    'execution',
    'dedupe',
    'git_hygiene',
    'verification',
    'concurrency',
    'chief_coordination',
  ];
  const scores = {};
  for (const d of dims) {
    const related = findings.filter((f) => f.dimension === d);
    if (!related.length) scores[d] = 'pass';
    else if (related.some((f) => f.severity === 'fail')) scores[d] = 'fail';
    else scores[d] = 'warn';
  }
  return scores;
}

export function formatMarkdown(report) {
  const lines = [
    '# Agent auditor report',
    '',
    `- **Repo:** ${report.repoRoot}`,
    `- **When:** ${report.generatedAt}`,
    `- **Window:** last ${report.sinceMinutes} minutes`,
    `- **Transcripts scanned:** ${report.scannedTranscripts}`,
    `- **chief:scan:** exit ${report.chiefExitCode}`,
    `- **Exit:** ${report.exitCode}`,
    '',
    '## Scores',
  ];
  for (const [k, v] of Object.entries(report.scores)) lines.push(`- **${k}:** ${v}`);
  lines.push('');
  if (!report.findings.length) {
    lines.push('No findings.');
    return lines.join('\n');
  }
  lines.push('## Findings');
  for (const f of report.findings) {
    lines.push(`### [${f.severity}] ${f.dimension}`);
    lines.push(`- ${f.message}`);
    if (f.skillPatch) lines.push(`- **Patch:** ${f.skillPatch}`);
    if (f.transcriptId) lines.push(`- **Transcript:** ${f.transcriptId}`);
    lines.push('');
  }
  return lines.join('\n');
}

export function writeAuditorArtifacts(report, { writeReport = true, appendSessionLog = true } = {}) {
  const auditorDir = join(report.repoRoot, '.git', 'auditor');
  try {
    mkdirSync(auditorDir, { recursive: true });
  } catch {
    return;
  }
  if (writeReport) {
    writeFileSync(join(auditorDir, 'auditor-report.md'), formatMarkdown(report), 'utf8');
  }
  if (appendSessionLog) {
    const summary = report.findings.length
      ? report.findings.map((f) => `[${f.severity}] ${f.message}`).join('; ')
      : 'pass';
    appendFileSync(
      join(auditorDir, 'session.log'),
      `${report.generatedAt}\texit=${report.exitCode}\t${summary}\n`,
      'utf8',
    );
  }
}
