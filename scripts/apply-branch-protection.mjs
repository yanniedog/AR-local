#!/usr/bin/env node
/** Update required status checks without replacing unrelated branch protections. */
import { spawnSync } from 'node:child_process';
import { applyStatusCheckPolicy } from './lib/branch-protection-policy.mjs';

function parseArgs(argv) {
  const options = { dryRun: false };
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--dry-run') options.dryRun = true;
    else if (arg === '--help' || arg === '-h') options.help = true;
    else if (arg === '--branch' && argv[i + 1]) options.branch = argv[++i];
    else if (arg.startsWith('--branch=')) options.branch = arg.slice('--branch='.length);
    else throw new Error(`Unknown or incomplete option: ${arg}`);
  }
  return options;
}

function ghJson(args, input) {
  const result = spawnSync('gh', args, {
    encoding: 'utf8', timeout: 120_000,
    ...(input === undefined ? {} : { input: JSON.stringify(input) }),
  });
  if (result.error || result.status !== 0) {
    throw new Error(result.error?.message || (result.stderr || result.stdout || '').trim()
      || `gh exited ${result.status}`);
  }
  return JSON.parse(result.stdout);
}

try {
  const options = parseArgs(process.argv);
  if (options.help) {
    console.log('Usage: npm run branch-protection:apply [-- --branch <default branch>] [--dry-run]');
    console.log('Requires existing status-check protection; defaults to the live repository default branch.');
  } else {
    const result = applyStatusCheckPolicy(options, { read: ghJson, write: ghJson });
    console.log(JSON.stringify(result, null, 2));
  }
} catch (error) {
  console.error(`apply-branch-protection: ${error.message}`);
  process.exitCode = 1;
}
