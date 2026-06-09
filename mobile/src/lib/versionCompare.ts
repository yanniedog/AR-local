/** Numeric semver compare: true when a < b ("1.0.0" < "1.1.0"). */
export function versionLt(a: string, b: string): boolean {
  const pa = a.split('.').map((n) => parseInt(n, 10) || 0);
  const pb = b.split('.').map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] ?? 0;
    const y = pb[i] ?? 0;
    if (x < y) return true;
    if (x > y) return false;
  }
  return false;
}

/** Compare native build numbers (Android versionCode / iOS CFBundleVersion). */
export function buildNumberLt(a: string, b: string): boolean {
  const na = parseInt(a, 10);
  const nb = parseInt(b, 10);
  if (Number.isNaN(na) || Number.isNaN(nb)) {
    return a < b;
  }
  return na < nb;
}

/** True when remote is strictly newer than installed (version, then build). */
export function isUpdateAvailable(
  installedVersion: string,
  installedBuild: string,
  remoteVersion: string,
  remoteBuild: string,
): boolean {
  if (versionLt(installedVersion, remoteVersion)) return true;
  if (versionLt(remoteVersion, installedVersion)) return false;
  return buildNumberLt(installedBuild, remoteBuild);
}
