#!/usr/bin/env node
/**
 * Lightweight reminder after subagent/parent stop when repo needs orchestrator.
 * Reads hook JSON on stdin; prints { followup_message } or {} on stdout.
 * Fail-open on errors (exit 0, empty object).
 */
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";

const repoRoot = process.cwd();

function run(cmd) {
  return execSync(cmd, { cwd: repoRoot, encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] }).trim();
}

function main() {
  try {
    readFileSync(0, "utf8"); // consume stdin (hook payload); no fields required yet
  } catch {
    // ignore
  }

  let dirty = false;
  let openPrCount = 0;
  try {
    dirty = Boolean(run("git status --porcelain"));
  } catch {
    // not a git repo or git missing
  }
  try {
    const out = run("gh pr list --state open --json number");
    const parsed = JSON.parse(out || "[]");
    openPrCount = Array.isArray(parsed) ? parsed.length : 0;
  } catch {
    // gh missing or not authenticated — skip PR signal
  }

  if (!dirty && openPrCount === 0) {
    console.log("{}");
    return;
  }

  const parts = [];
  if (dirty) parts.push("uncommitted changes");
  if (openPrCount > 0) parts.push(`${openPrCount} open PR(s)`);

  const msg =
    `Workflow orchestrator: ${parts.join(" and ")} detected. ` +
    "Run one cycle per .cursor/skills/workflow-orchestrator/SKILL.md " +
    "(Task generalPurpose, run_in_background unless waived). " +
    "Enforce one PR per task; do not bundle unrelated files.";

  console.log(JSON.stringify({ followup_message: msg }));
}

main();
