"use strict";

const { existsSync, readFileSync, readdirSync, writeFileSync, mkdirSync } = require("node:fs");
const { execFileSync } = require("node:child_process");
const { join } = require("node:path");
const { versionTag, releaseTitle } = require("./app-release-meta-pure.cjs");

const CHANGELOG_SUMMARY_ASSET = "changelog-summary.json";
const GIT_TIMEOUT_MS = 15_000;

function changelogSummaryUrl(repo, tag) {
  return `https://github.com/${repo}/releases/download/${tag}/${CHANGELOG_SUMMARY_ASSET}`;
}

function releasePageUrl(repo, version) {
  return `https://github.com/${repo}/releases/tag/${versionTag(version)}`;
}

function parseVersionParts(version) {
  return String(version)
    .trim()
    .split(".")
    .map((n) => parseInt(n, 10) || 0);
}

function compareVersion(a, b) {
  const pa = parseVersionParts(a);
  const pb = parseVersionParts(b);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] ?? 0;
    const y = pb[i] ?? 0;
    if (x < y) return -1;
    if (x > y) return 1;
  }
  return 0;
}

function versionLt(a, b) {
  return compareVersion(a, b) < 0;
}

function versionGt(a, b) {
  return compareVersion(a, b) > 0;
}

function versionEq(a, b) {
  return compareVersion(a, b) === 0;
}

function normalizeBullet(value) {
  if (typeof value === "string") return { text: value.trim() };
  if (value && typeof value === "object" && typeof value.text === "string") {
    const bullet = { text: value.text.trim() };
    if (Array.isArray(value.children) && value.children.length) {
      bullet.children = value.children.map(normalizeBullet);
    }
    return bullet;
  }
  return null;
}

function loadVersionEntry(filePath) {
  const raw = JSON.parse(readFileSync(filePath, "utf8"));
  if (!raw || typeof raw.version !== "string") {
    throw new Error(`Invalid changelog entry (missing version): ${filePath}`);
  }
  const entry = {
    version: raw.version.trim(),
    summaryBullets: Array.isArray(raw.summaryBullets)
      ? raw.summaryBullets.map((s) => String(s).trim()).filter(Boolean)
      : [],
  };
  if (raw.date) entry.date = String(raw.date).trim();
  if (Array.isArray(raw.sections)) {
    entry.sections = raw.sections
      .map((section) => {
        if (!section || typeof section.title !== "string") return null;
        const bullets = Array.isArray(section.bullets)
          ? section.bullets.map(normalizeBullet).filter(Boolean)
          : [];
        return { title: section.title.trim(), bullets };
      })
      .filter(Boolean);
  }
  return entry;
}

function versionsDir(mobileRoot) {
  return join(mobileRoot, "changelog", "versions");
}

function versionEntryPath(mobileRoot, version) {
  return join(versionsDir(mobileRoot), `${version}.json`);
}

function loadVersionEntryIfExists(mobileRoot, version) {
  const path = versionEntryPath(mobileRoot, version);
  if (!existsSync(path)) return null;
  return loadVersionEntry(path);
}

function loadAllVersionEntries(mobileRoot) {
  const dir = versionsDir(mobileRoot);
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((name) => name.endsWith(".json"))
    .map((name) => loadVersionEntry(join(dir, name)))
    .sort((a, b) => compareVersion(a.version, b.version));
}

function buildChangelogManifest({ repo, mobileRoot, entries }) {
  const list = entries ?? loadAllVersionEntries(mobileRoot);
  return {
    schema_version: 1,
    repo,
    generated_at: new Date().toISOString(),
    versions: list.map((entry) => ({
      version: entry.version,
      ...(entry.date ? { date: entry.date } : {}),
      summaryBullets: entry.summaryBullets,
      releaseUrl: releasePageUrl(repo, entry.version),
    })),
  };
}

function selectCumulativeSummaries(manifest, fromExclusive, toInclusive) {
  return (manifest.versions ?? []).filter(
    (row) => versionGt(row.version, fromExclusive) && !versionGt(row.version, toInclusive),
  );
}

function renderBulletMarkdown(bullets, depth = 0) {
  const indent = "  ".repeat(depth);
  const lines = [];
  for (const bullet of bullets) {
    lines.push(`${indent}- ${bullet.text}`);
    if (bullet.children?.length) lines.push(renderBulletMarkdown(bullet.children, depth + 1));
  }
  return lines.filter(Boolean).join("\n");
}

function renderGithubReleaseBody({ entry, buildNumber, repo }) {
  const lines = [`## ${entry.version} (build ${buildNumber})`, ""];
  if (entry.date) lines.push(`Released **${entry.date}**.`, "");
  lines.push("Preview APK published by **mobile-android-apk** (GitHub Actions).", "");
  if (entry.summaryBullets.length) {
    lines.push("### Highlights", "");
    for (const bullet of entry.summaryBullets) lines.push(`- ${bullet}`);
    lines.push("");
  }
  for (const section of entry.sections ?? []) {
    if (!section.bullets.length) continue;
    lines.push(
      `<details>`,
      `<summary>${section.title}</summary>`,
      "",
      renderBulletMarkdown(section.bullets),
      "",
      `</details>`,
      "",
    );
  }
  lines.push(
    `<details>`,
    `<summary>Install</summary>`,
    "",
    "Scan **app-preview-qr.png** with Android Chrome, or open **install.html** on this release.",
    "",
    `- Versioned tag: [\`${versionTag(entry.version)}\`](${releasePageUrl(repo, entry.version)})`,
    `- Rolling manifest: [\`${CHANGELOG_SUMMARY_ASSET}\`](${changelogSummaryUrl(repo, "app-apk-latest")})`,
    "",
    `</details>`,
    "",
    `_Build ${buildNumber}_`,
    "",
  );
  return lines.join("\n");
}

function renderRollingReleaseNotes({ version, buildNumber, repo, mobileRoot }) {
  const entry = loadVersionEntryIfExists(mobileRoot, version);
  const highlights = entry?.summaryBullets?.length
    ? entry.summaryBullets.map((b) => `- ${b}`).join("\n")
    : "_See versioned release for details._";
  return [
    "## Rolling preview APK",
    "",
    `Current build: **${version}** (build ${buildNumber})`,
    "",
    "In-app self-update reads `app-apk-latest.json` and `changelog-summary.json` from this release.",
    "",
    "### Highlights",
    "",
    highlights,
    "",
    `Full changelog: [${versionTag(version)}](${releasePageUrl(repo, version)})`,
    "",
  ].join("\n");
}

function gitExec(repoRoot, args) {
  return execFileSync("git", args, {
    encoding: "utf8",
    cwd: repoRoot,
    timeout: GIT_TIMEOUT_MS,
  });
}

function findPreviousVersionTag(mobileRoot, version) {
  const repoRoot = join(mobileRoot, "..");
  const current = versionTag(version);
  try {
    const raw = gitExec(repoRoot, ["tag", "--list", "app-v*", "--sort=-version:refname"]);
    return raw
      .trim()
      .split("\n")
      .map((t) => t.trim())
      .filter(Boolean)
      .find((t) => t !== current) ?? null;
  } catch {
    return null;
  }
}

function stripCommitPrefix(line) {
  return line.replace(/^-\s+/, "").trim();
}

function generateStubEntry({ version, mobileRoot, repo }) {
  const repoRoot = join(mobileRoot, "..");
  const prevTag = findPreviousVersionTag(mobileRoot, version);
  const logArgs = prevTag
    ? ["log", `${prevTag}..HEAD`, "--pretty=format:%s", "--", "mobile/"]
    : ["log", "--pretty=format:%s", "-30", "--", "mobile/"];
  let subjects = [];
  try {
    const raw = gitExec(repoRoot, logArgs).trim();
    subjects = raw ? raw.split("\n").map((s) => s.trim()).filter(Boolean) : [];
  } catch {
    subjects = [];
  }
  const unique = [...new Set(subjects)];
  const summaryBullets = unique.slice(0, 5).map(stripCommitPrefix);
  if (!summaryBullets.length) summaryBullets.push(`Maintenance release ${version}`);
  return {
    version,
    date: new Date().toISOString().slice(0, 10),
    summaryBullets,
    sections: [
      { title: "Changes", bullets: unique.map((subject) => ({ text: stripCommitPrefix(subject) })) },
      {
        title: "Release metadata",
        bullets: [
          { text: `Repository: ${repo}` },
          { text: `Version tag: ${versionTag(version)}` },
          ...(prevTag ? [{ text: `Since tag: ${prevTag}` }] : []),
        ],
      },
    ],
  };
}

function writeVersionEntry(entry, mobileRoot) {
  const dir = versionsDir(mobileRoot);
  mkdirSync(dir, { recursive: true });
  const path = versionEntryPath(mobileRoot, entry.version);
  writeFileSync(path, JSON.stringify(entry, null, 2) + "\n", "utf8");
  return path;
}

function ensureVersionEntry({ version, mobileRoot, repo, force = false }) {
  const existing = loadVersionEntryIfExists(mobileRoot, version);
  if (existing && !force) return { created: false, entry: existing };
  const entry = generateStubEntry({ version, mobileRoot, repo });
  const path = writeVersionEntry(entry, mobileRoot);
  return { created: true, path, entry };
}

module.exports = {
  CHANGELOG_SUMMARY_ASSET,
  changelogSummaryUrl,
  releasePageUrl,
  compareVersion,
  versionLt,
  versionGt,
  versionEq,
  loadVersionEntry,
  loadVersionEntryIfExists,
  loadAllVersionEntries,
  buildChangelogManifest,
  selectCumulativeSummaries,
  renderBulletMarkdown,
  renderGithubReleaseBody,
  renderRollingReleaseNotes,
  ensureVersionEntry,
  writeVersionEntry,
  generateStubEntry,
  versionsDir,
  versionEntryPath,
};
