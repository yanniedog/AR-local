/** @param {string} version semver x.y.z */
function bumpPatchVersion(version) {
  const parts = String(version)
    .trim()
    .split('.')
    .map((n) => parseInt(n, 10) || 0);
  while (parts.length < 3) {
    parts.push(0);
  }
  if (parts.some((n) => n < 0 || !Number.isFinite(n))) {
    return version;
  }
  parts[2] += 1;
  return parts.join('.');
}

module.exports = { bumpPatchVersion };
