#!/usr/bin/env node
import { appendFileSync, readFileSync } from 'node:fs';
import { discoverGatePrs, publishRequiredGate, validPrNumber } from './lib/pr-required-gate.mjs';

try {
  const repository = process.env.GITHUB_REPOSITORY;
  if (process.argv.includes('--discover')) {
    const event = JSON.parse(readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8'));
    const prs = discoverGatePrs(event, process.env.GITHUB_EVENT_NAME, repository);
    if (!process.env.GITHUB_OUTPUT) throw new Error('Missing GitHub output file');
    appendFileSync(process.env.GITHUB_OUTPUT, 'prs=' + JSON.stringify(prs) + '\n');
    console.log('Gate targets: ' + prs.join(', '));
  } else if (process.argv.includes('--publish')) {
    const result = publishRequiredGate(validPrNumber(process.env.GATE_PR), { repository,
      detailsUrl: 'https://github.com/' + repository + '/actions/runs/' + process.env.GITHUB_RUN_ID });
    console.log(JSON.stringify(result));
    if (process.env.GITHUB_STEP_SUMMARY) {
      appendFileSync(process.env.GITHUB_STEP_SUMMARY,
        (result.title || result.detail) + '\n\n' + (result.summary || '') + '\n');
    }
  } else throw new Error('Use --discover or --publish');
} catch (error) {
  console.error('Required gate: ' + error.message);
  process.exitCode = 1;
}
