#!/usr/bin/env node
import { appendFileSync, readFileSync } from 'node:fs';
import { discoverGatePrs, publishRequiredGate, retirePriorEventGate, validPrNumber } from './lib/pr-required-gate.mjs';
import { mergedDispatch, publishMergedGate } from './lib/pr-merged-gate.mjs';

try {
  const repository = process.env.GITHUB_REPOSITORY;
  const event = JSON.parse(readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8'));
  const merged = mergedDispatch(event, process.env.GITHUB_EVENT_NAME, repository,
    process.env.GITHUB_EVENT_NAME === 'workflow_dispatch' ? validPrNumber(event.inputs?.pr_number) : null);
  if (process.argv.includes('--discover')) {
    const prs = discoverGatePrs(event, process.env.GITHUB_EVENT_NAME, repository);
    if (!process.env.GITHUB_OUTPUT) throw new Error('Missing GitHub output file');
    appendFileSync(process.env.GITHUB_OUTPUT, 'prs=' + JSON.stringify(prs) + '\n');
    console.log('Gate targets: ' + prs.join(', '));
  } else if (process.argv.includes('--retire-event')) {
    console.log(JSON.stringify(retirePriorEventGate(event, process.env.GITHUB_EVENT_NAME, { repository })));
  } else if (process.argv.includes('--publish')) {
    const prNumber = validPrNumber(process.env.GATE_PR);
    if (merged && prNumber !== validPrNumber(event.inputs.pr_number)) throw new Error('Merged dispatch target mismatch');
    const result = merged ? publishMergedGate(prNumber, { repository, ...merged,
      reporterSha: process.env.GITHUB_SHA, runId: Number(process.env.GITHUB_RUN_ID),
      runAttempt: Number(process.env.GITHUB_RUN_ATTEMPT) }) : publishRequiredGate(prNumber, { repository,
      detailsUrl: 'https://github.com/' + repository + '/actions/runs/' + process.env.GITHUB_RUN_ID });
    console.log(JSON.stringify(result));
    if (process.env.GITHUB_STEP_SUMMARY) {
      appendFileSync(process.env.GITHUB_STEP_SUMMARY,
        (result.title || result.detail) + '\n\n' + (result.summary || '') + '\n');
    }
  } else throw new Error('Use --discover, --retire-event, or --publish');
} catch (error) {
  console.error('Required gate: ' + error.message);
  process.exitCode = 1;
}
