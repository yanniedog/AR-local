#!/usr/bin/env node
/**
 * Ensure mobile/changelog/versions/{semver}.json exists (git-backed stub if missing).
 *
 * Usage: node scripts/ensure-changelog-entry.mjs [--version 1.0.3] [--repo owner/name]
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { ensureVersionEntry } = require("./changelog-lib.cjs");

const mobileRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

const vIdx = process.argv.indexOf("--version");
const repoArgIdx = process.argv.indexOf("--repo");
const repo =
  (repoArgIdx >= 0 ? process.argv[repoArgIdx + 1] : process.env.GITHUB_REPOSITORY)?.trim() ||
  "yanniedog/AR-local";
const version =
  (vIdx >= 0 ? process.argv[vIdx + 1] : null)?.trim() ||
  String(JSON.parse(readFileSync(join(mobileRoot, "app.json"), "utf8")).expo?.version ?? "1.0.0").trim();

const result = ensureVersionEntry({ version, mobileRoot, repo });
const action = result.created ? "created" : "exists";
console.log(`changelog: ${action} ${version}.json (${result.entry.summaryBullets.length} summary bullets)`);
