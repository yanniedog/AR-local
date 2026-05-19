#!/usr/bin/env node
/**
 * Agent auditor — meta-monitor for chief, orchestrator, and subagent behavior.
 *
 * Usage:
 *   node scripts/agent-auditor-scan.mjs [--since-minutes 60] [--json] [--hook] [--no-write]
 *   npm run agent:auditor
 *
 * Exit 0 pass, 1 warnings, 2 critical failures.
 */
import { parseArgs } from 'node:util';
import {
  repoRoot,
  runAudit,
  formatMarkdown,
  writeAuditorArtifacts,
} from './lib/agent-auditor-lib.mjs';

const { values } = parseArgs({
  options: {
    'since-minutes': { type: 'string', default: '60' },
    json: { type: 'boolean', default: false },
    markdown: { type: 'boolean', default: false },
    hook: { type: 'boolean', default: false },
    'no-write': { type: 'boolean', default: false },
  },
});

function main() {
  const root = repoRoot();
  process.chdir(root);
  const sinceMinutes = Math.max(5, parseInt(values['since-minutes'], 10) || 60);
  const hook = Boolean(values.hook);
  const report = runAudit({ repoRoot: root, sinceMinutes, hook });

  if (!values['no-write']) {
    writeAuditorArtifacts(report, { writeReport: !hook, appendSessionLog: true });
  }

  if (values.json || hook) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(formatMarkdown(report));
  }

  process.exit(report.exitCode);
}

main();
