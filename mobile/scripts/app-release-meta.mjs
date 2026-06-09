/**
 * Release naming, changelog, and git-backed notes for Android APK GitHub releases.
 *
 * Tag scheme: app-v{semver}  e.g. app-v1.0.0
 * Release title: Australian Rates app – {version} (Android)
 */
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { versionTag, releaseTitle, extractChangelogSection } = require("./app-release-meta-pure.cjs");

export { versionTag, releaseTitle, extractChangelogSection };

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const mobileRoot = join(__dirname, "..");
const repoRoot = join(mobileRoot, "..");

const GIT_TIMEOUT_MS = 15_000;

/** @param {string[]} args */
function gitExec(args) {
  return execFileSync("git", args, {
    encoding: "utf8",
    cwd: repoRoot,
    timeout: GIT_TIMEOUT_MS,
  });
}

export const ROLLING_TAG = "app-apk-latest";
export const APK_ASSET = "app-preview.apk";
export const MANIFEST_ASSET = "app-apk-latest.json";
export const QR_ASSET = "app-preview-qr.png";
export const INSTALL_HTML = "install.html";

/** @param {string} repo owner/name @param {string} tag */
export function apkDownloadUrl(repo, tag) {
  return `https://github.com/${repo}/releases/download/${tag}/${APK_ASSET}`;
}

/** @param {string} repo @param {string} tag */
export function qrReleaseUrl(repo, tag) {
  return `https://github.com/${repo}/releases/download/${tag}/${QR_ASSET}`;
}

/** @param {string} repo @param {string} tag */
export function installReleaseUrl(repo, tag) {
  return `https://github.com/${repo}/releases/download/${tag}/${INSTALL_HTML}`;
}

/** @param {string} repo @param {string} tag */
export function manifestReleaseUrl(repo, tag) {
  return `https://github.com/${repo}/releases/download/${tag}/${MANIFEST_ASSET}`;
}

/** @param {string} mobileRoot */
export function readAppJson(mobileRoot) {
  return JSON.parse(readFileSync(join(mobileRoot, "app.json"), "utf8"));
}

/** @param {string} mobileRoot */
export function readAppJsonVersion(mobileRoot) {
  return readAppJson(mobileRoot).expo?.version ?? "1.0.0";
}

/** @param {string} mobileRoot */
export function readAppJsonBuildNumber(mobileRoot) {
  const code = readAppJson(mobileRoot).expo?.android?.versionCode;
  return code != null ? String(code) : "0";
}

/**
 * @param {string} version
 * @returns {string | null} previous app-v* tag (excluding current)
 */
export function findPreviousVersionTag(version) {
  const current = versionTag(version);
  try {
    const raw = gitExec(["tag", "--list", "app-v*", "--sort=-version:refname"]);
    const tags = raw
      .trim()
      .split("\n")
      .map((t) => t.trim())
      .filter(Boolean);
    return tags.find((t) => t !== current) ?? null;
  } catch {
    return null;
  }
}

/**
 * @param {{ version: string, buildNumber: string, mobileRoot: string }} opts
 */
export function generateReleaseNotes({ version, buildNumber, mobileRoot }) {
  const changelogPath = join(mobileRoot, "CHANGELOG.md");
  if (existsSync(changelogPath)) {
    const section = extractChangelogSection(readFileSync(changelogPath, "utf8"), version);
    if (section) {
      return `${section}\n_Build ${buildNumber}_\n`;
    }
  }

  const prevTag = findPreviousVersionTag(version);
  const logArgs = prevTag
    ? ["log", `${prevTag}..HEAD`, "--pretty=format:- %s (%h)", "--", "mobile/"]
    : ["log", "--pretty=format:- %s (%h)", "-30", "--", "mobile/"];

  let commits = "";
  try {
    commits = gitExec(logArgs).trim();
  } catch {
    commits = "";
  }

  const lines = [
    `## ${version} (build ${buildNumber})`,
    "",
    "Preview APK published by **mobile-android-apk** (GitHub Actions).",
    "",
  ];
  if (commits) {
    lines.push("### Changes since last app release", "", commits, "");
  } else {
    lines.push("_No mobile commits since the previous app-v release tag._", "");
  }
  lines.push(
    "### Install",
    "",
    "Scan **app-preview-qr.png** with Android Chrome, or open **install.html** on this release.",
    "",
  );
  return lines.join("\n");
}
