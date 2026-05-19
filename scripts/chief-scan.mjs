#!/usr/bin/env node
/**
 * Chief coordination scan — repo health before delegating subagents.
 *
 * Usage:
 *   node scripts/chief-scan.mjs
 *   npm run chief:scan
 *
 * Exit 0 — no blocking issues (warnings may still print).
 * Exit 1 — dirty main, path clash between agent branches, or open PR merge conflict.
 */
import { execSync } from 'node:child_process';
import { readdirSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

function sh(cmd) {
  try {
    return execSync(cmd, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  } catch (e) {
    return (e.stdout || e.stderr || '').trim();
  }
}

function shJson(cmd) {
  const raw = sh(cmd);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function repoRoot() {
  return sh('git rev-parse --show-toplevel') || process.cwd();
}

function branchFiles(branch) {
  const out = sh(`git diff --name-only origin/main...${branch} 2>nul`);
  if (!out) return [];
  return out.split(/\r?\n/).filter(Boolean);
}

function listAgentBranches() {
  const out = sh('git branch --list agent/*');
  if (!out) return [];
  return out
    .split(/\r?\n/)
    .map((l) => l.replace(/^\*?\s+/, '').trim())
    .filter((b) => b.startsWith('agent/'));
}

function listWorktrees() {
  const out = sh('git worktree list --porcelain');
  if (!out) return [];
  const trees = [];
  let cur = {};
  for (const line of out.split(/\r?\n/)) {
    if (line.startsWith('worktree ')) {
      if (cur.path) trees.push(cur);
      cur = { path: line.slice(9) };
    } else if (line.startsWith('branch ')) {
      cur.branch = line.slice(7).replace(/^refs\/heads\//, '');
    } else if (line === '') {
      if (cur.path) trees.push(cur);
      cur = {};
    }
  }
  if (cur.path) trees.push(cur);
  return trees;
}

function listStashes() {
  const out = sh('git stash list');
  if (!out) return [];
  return out.split(/\r?\n/).filter(Boolean);
}

function openPrs() {
  return shJson('gh pr list --state open --json number,title,headRefName,mergeable,url') || [];
}

function recentSubagentIds(projectSlug, withinMin = 120) {
  const base = join(homedir(), '.cursor', 'projects', projectSlug, 'agent-transcripts');
  const ids = [];
  const cutoff = Date.now() - withinMin * 60 * 1000;
  try {
    for (const dir of readdirSync(base)) {
      const subDir = join(base, dir, 'subagents');
      try {
        for (const file of readdirSync(subDir)) {
          if (!file.endsWith('.jsonl')) continue;
          const full = join(subDir, file);
          if (statSync(full).mtimeMs >= cutoff) {
            ids.push(file.replace(/\.jsonl$/, ''));
          }
        }
      } catch {
        /* no subagents dir */
      }
    }
  } catch {
    /* no transcripts */
  }
  return ids.sort();
}

function projectSlugFromRoot(root) {
  const norm = root.replace(/\\/g, '/').replace(/:/g, '-').replace(/^\/+/, '');
  return norm.toLowerCase();
}

function main() {
  const root = repoRoot();
  process.chdir(root);

  const branch = sh('git branch --show-current');
  const porcelain = sh('git status --porcelain');
  const dirtyFiles = porcelain
    ? porcelain.split(/\r?\n/).map((l) => l.slice(3).trim()).filter(Boolean)
    : [];

  const worktrees = listWorktrees();
  const stashes = listStashes();
  const prs = openPrs();
  const agentBranches = listAgentBranches();
  const branchPaths = new Map();
  for (const b of agentBranches) {
    const files = branchFiles(b);
    if (files.length) branchPaths.set(b, new Set(files));
  }

  const pathClashes = [];
  const branches = [...branchPaths.keys()];
  for (let i = 0; i < branches.length; i++) {
    for (let j = i + 1; j < branches.length; j++) {
      const a = branches[i];
      const b = branches[j];
      const overlap = [...branchPaths.get(a)].filter((f) => branchPaths.get(b).has(f));
      if (overlap.length) {
        pathClashes.push({ a, b, files: overlap.slice(0, 8), more: overlap.length - 8 });
      }
    }
  }

  const branchPrMap = new Map(prs.map((p) => [p.headRefName, p]));
  const branchMismatch =
    branch && branch.startsWith('agent/') && !branchPrMap.has(branch)
      ? { branch, note: 'no open PR for current agent branch' }
      : null;

  const prHeadMismatch = prs
    .filter((p) => {
      const local = sh(`git rev-parse ${p.headRefName} 2>nul`);
      const remote = sh(`git rev-parse origin/${p.headRefName} 2>nul`);
      return local && remote && local !== remote;
    })
    .map((p) => p.number);

  const mergeConflicts = prs.filter((p) => p.mergeable === 'CONFLICTING').map((p) => p.number);
  const dirtyMain = branch === 'main' && dirtyFiles.length > 0;

  const worktreeDupes = [];
  const branchWorktrees = new Map();
  for (const wt of worktrees) {
    if (!wt.branch) continue;
    if (!branchWorktrees.has(wt.branch)) branchWorktrees.set(wt.branch, []);
    branchWorktrees.get(wt.branch).push(wt.path);
  }
  for (const [b, paths] of branchWorktrees) {
    if (paths.length > 1) worktreeDupes.push({ branch: b, paths });
  }

  const slug = projectSlugFromRoot(root);
  const recentIds = recentSubagentIds(slug);

  console.log('=== chief:scan ===');
  console.log(`repo: ${root}`);
  console.log(`branch: ${branch}${dirtyFiles.length ? ' (dirty)' : ' (clean)'}`);
  if (dirtyFiles.length) {
    console.log('dirty files:');
    for (const f of dirtyFiles.slice(0, 20)) console.log(`  ${f}`);
    if (dirtyFiles.length > 20) console.log(`  ... +${dirtyFiles.length - 20} more`);
  }

  console.log('\nopen PRs:');
  if (!prs.length) console.log('  (none)');
  for (const p of prs) {
    const flag = p.mergeable === 'CONFLICTING' ? ' CONFLICT' : '';
    console.log(`  #${p.number} ${p.headRefName}${flag} — ${p.title}`);
  }

  console.log('\nworktrees:');
  for (const wt of worktrees) {
    console.log(`  ${wt.path} [${wt.branch || 'detached'}]`);
  }

  if (stashes.length) {
    console.log(`\nstashes: ${stashes.length}`);
    for (const s of stashes.slice(0, 8)) console.log(`  ${s}`);
    if (stashes.length > 8) console.log(`  ... +${stashes.length - 8} more`);
  }

  if (recentIds.length) {
    console.log('\nrecent subagent transcript IDs (2h):');
    console.log(`  ${recentIds.join(', ')}`);
  }

  if (pathClashes.length) {
    console.log('\npath clashes (agent branches vs origin/main):');
    for (const c of pathClashes) {
      console.log(`  ${c.a} <> ${c.b}: ${c.files.join(', ')}${c.more > 0 ? ` (+${c.more})` : ''}`);
    }
  }

  if (worktreeDupes.length) {
    console.log('\nworktree duplicates (same branch, multiple trees):');
    for (const d of worktreeDupes) {
      console.log(`  ${d.branch}: ${d.paths.join(' | ')}`);
    }
  }

  if (branchMismatch) {
    console.log(`\nbranch/PR note: ${branchMismatch.branch} — ${branchMismatch.note}`);
  }
  if (prHeadMismatch.length) {
    console.log(`\nbranch tip mismatch vs origin for PR branch(es): #${prHeadMismatch.join(', #')}`);
  }

  let exitCode = 0;
  const blockers = [];
  if (dirtyMain) blockers.push('dirty main branch');
  if (pathClashes.length) blockers.push('agent branch path overlap');
  if (mergeConflicts.length) blockers.push(`merge conflicts on PR #${mergeConflicts.join(', #')}`);

  if (blockers.length) {
    console.log(`\nBLOCKERS: ${blockers.join('; ')}`);
    exitCode = 1;
  } else {
    console.log('\nOK: no chief blockers');
  }

  process.exit(exitCode);
}

main();
