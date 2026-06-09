"use strict";

function versionTag(version) {
  return `app-v${version}`;
}

function releaseTitle(version) {
  return `Australian Rates app \u2013 ${version} (Android)`;
}

function extractChangelogSection(content, version) {
  const heading = new RegExp(`^##\\s+\\[?${version.replace(/\./g, '\\.')}\\]?`, 'm');
  const match = content.match(heading);
  if (!match || match.index == null) {
    return null;
  }
  const start = match.index;
  const rest = content.slice(start + match[0].length);
  const nextHeading = rest.search(/^##\s+/m);
  const body = (nextHeading >= 0 ? rest.slice(0, nextHeading) : rest).trim();
  if (!body) {
    return null;
  }
  return `## ${version}\n\n${body}\n`;
}

module.exports = { versionTag, releaseTitle, extractChangelogSection };
