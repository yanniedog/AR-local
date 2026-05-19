#!/usr/bin/env node
/** Disabled by default. Set AR_LOCAL_COORDINATION_HOOKS=1 and register in hooks.json to re-enable. */
import { execSync } from "node:child_process";
const repoRoot = process.cwd();
const EXEC_TIMEOUT_MS = 2000;
const EXEC_MAX_BUFFER = 1024 * 1024;
function main() {
  if (process.env.AR_LOCAL_COORDINATION_HOOKS !== "1") {
    console.log("{}");
    return;
  }
  runWithCoordinationHooks();
}
function run(cmd) {
  try {
    return execSync(cmd, { cwd: repoRoot, encoding: "utf8", stdio: ["pipe", "pipe", "pipe"], timeout: EXEC_TIMEOUT_MS, maxBuffer: EXEC_MAX_BUFFER }).trim();
  } catch (error) {
    if (error?.code === "ETIMEDOUT" || error?.signal === "SIGTERM") return "";
    throw error;
  }
}
function githubRepoSlug() {
  try {
    const url = run("git config --get remote.origin.url");
    const match = url.match(/github\.com[:/]([^/]+\/[^/.]+)/);
    return match ? match[1].replace(/\.git$/, "") : "";
  } catch { return ""; }
}
function runWithCoordinationHooks() {
  let dirty = false;
  let openPrCount = 0;
  try { dirty = Boolean(run("git status --porcelain")); } catch {}
  try {
    const slug = githubRepoSlug();
    const repoFlag = slug ? ` --repo ${slug}` : "";
    const parsed = JSON.parse(run(`gh pr list --state open --json number${repoFlag}`) || "[]");
    openPrCount = Array.isArray(parsed) ? parsed.length : 0;
  } catch {}
  if (!dirty && openPrCount === 0) { console.log("{}"); return; }
  const parts = [];
  if (dirty) parts.push("uncommitted changes");
  if (openPrCount > 0) parts.push(`${openPrCount} open PR(s)`);
  const msg = `Chief agent: ${parts.join(" and ")} detected. Run one coordination cycle per .cursor/skills/chief-agent/SKILL.md.`;
  console.log(JSON.stringify({ followup_message: msg }));
}
main();
