#!/usr/bin/env node
/**
 * Regenerate mobile/changelog/manifest.json from mobile/changelog/versions/*.json
 *
 * Usage: node scripts/build-changelog-manifest.mjs [--repo owner/name]
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { buildChangelogManifest } = require("./changelog-lib.cjs");

const mobileRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const changelogRoot = join(mobileRoot, "changelog");

const repoArgIdx = process.argv.indexOf("--repo");
const repo =
  (repoArgIdx >= 0 ? process.argv[repoArgIdx + 1] : process.env.GITHUB_REPOSITORY)?.trim() ||
  "yanniedog/AR-local";

const manifest = buildChangelogManifest({ repo, mobileRoot });
mkdirSync(changelogRoot, { recursive: true });
writeFileSync(join(changelogRoot, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
console.log(`changelog: wrote manifest.json (${manifest.versions.length} versions)`);
