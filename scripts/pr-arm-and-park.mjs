#!/usr/bin/env node
import { resolvePrNumber } from './lib/pr-gates-lib.mjs';
import { armAndParkOnce } from './lib/pr-arm-and-park-lib.mjs';

function parseArgs(argv) {
  const out = {
    pr: null,
    json: false,
    dryRun: false,
    skipArm: false,
    skipSync: false,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--json') out.json = true;
    else if (arg === '--dry-run') out.dryRun = true;
    else if (arg === '--skip-arm') out.skipArm = true;
    else if (arg === '--skip-sync') out.skipSync = true;
    else if (arg === '--pr' && argv[i + 1]) out.pr = Number(argv[++i]);
    else if (arg.startsWith('--pr=')) out.pr = Number(arg.slice(5));
    else if (arg === '--help' || arg === '-h') out.help = true;
  }
  if (out.pr != null && (!Number.isInteger(out.pr) || out.pr <= 0)) {
    out.prError = 'invalid --pr (positive integer required)';
  }
  return out;
}

function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log(`Usage: npm run pr:arm-and-park -- [--pr N] [--json] [--dry-run]

One shot: verify the exact default base, explicitly promote a draft, sync when behind,
arm squash auto-merge, and classify the remaining state.

Exit 0 ready or merged; 2 waiting on CI; 3 actionable; 1 hard error.
Agents never use --watch or sleep-poll loops.`);
    process.exit(0);
  }
  if (args.prError) {
    console.error(`pr:arm-and-park: ${args.prError}`);
    process.exit(1);
  }

  let pr;
  try {
    const resolved = resolvePrNumber(args.pr);
    if (resolved.error) throw new Error(resolved.error);
    pr = resolved.pr.number;
  } catch (error) {
    console.error(`pr:arm-and-park: ${error.message}`);
    process.exit(1);
  }

  const result = armAndParkOnce(pr, args);
  if (args.json) console.log(JSON.stringify({ pr, ...result }, null, 2));
  if (result.mode === 'error') {
    if (!args.json) console.error(`pr:arm-and-park: ${result.error}`);
    process.exit(1);
  }
  if (!args.json) {
    const outcome = result.merged ? 'MERGED' : result.mode.toUpperCase();
    console.log(
      `pr:arm-and-park: PR #${pr} ${outcome} `
      + `(auto-merge ${result.autoMergeArmed ? 'armed' : 'not armed'})`,
    );
    for (const gate of result.classification?.actionable || []) {
      console.error(`  actionable [${gate.id}] ${gate.detail || ''}`);
    }
    for (const gate of result.classification?.waiting || []) {
      console.log(`  waiting [${gate.id}] ${gate.detail || ''}`);
    }
  }
  process.exit(result.mode === 'ready' ? 0 : result.mode === 'waiting' ? 2 : 3);
}

main();
