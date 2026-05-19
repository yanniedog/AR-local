#!/usr/bin/env node
/**
 * Lightweight reminder after subagent/parent stop when repo needs coordination.
 * Chief-first message; chief delegates ship bar to workflow-orchestrator.
 * Hook JSON on stdin is optional; prints { followup_message } or {} on stdout.
 * Fail-open on errors (exit 0, empty object).
 */
import { execSync } from "node:child_process";

const repoRoot = process.cwd();
const EXEC_TIMEOUT_MS = 2000;
const EXEC_MAX_BUFFER = 1024 * 1024;

function run(cmd) {
  try {
    return execSync(cmd, {
      cwd: repoRoot,
      encoding: "utf8",
      stdio: ["pipe", "pipe", "pipe"],
      timeout: EXEC_TIMEOUT_MS,
      maxBuffer: EXEC_MAX_BUFFER,
    }).trim();
  } catch (error) {
    if (error && (error.code === "ETIMEDOUT" || error.signal === "SIGTERM")) {
      return "";
    }
    throw error;
  }
}

function githubRepoSlug() {
  try {
    const url = run("git config --get remote.origin.url");
    const match = url.match(/github\.com[:/]([^/]+\/[^/.]+)/);
    return match ? match[1].replace(/\.git$/, "") : "";
  } catch {
    return "";
  }
}

function main() {
  let dirty = false;
  let openPrCount = 0;
  try {
    dirty = Boolean(run("git status --porcelain"));
  } catch {
    // not a git repo or git missing
  }
  try {
    const slug = githubRepoSlug();
    const repoFlag = slug ? ` --repo ${slug}` : "";
    const out = run(`gh pr list --state open --json number${repoFlag}`);
    const parsed = JSON.parse(out || "[]");
    openPrCount = Array.isArray(parsed) ? parsed.length : 0;
  } catch {
    // gh missing, not authenticated, or timed out — skip PR signal
  }

  if (!dirty && openPrCount === 0) {
    console.log("{}");
    return;
  }

  const parts = [];
  if (dirty) parts.push("uncommitted changes");
  if (openPrCount > 0) parts.push(`${openPrCount} open PR(s)`);

  const msg =
    `Chief agent: ${parts.join(" and ")} detected. ` +
    "Run one coordination cycle per .cursor/skills/chief-agent/SKILL.md " +
    "(Task generalPurpose, run_in_background unless waived). " +
    "Chief dedupes locks and delegates ship bar to workflow-orchestrator; " +
    "one PR per task; do not bundle unrelated files.";

  console.log(JSON.stringify({ followup_message: msg }));
}

main();
