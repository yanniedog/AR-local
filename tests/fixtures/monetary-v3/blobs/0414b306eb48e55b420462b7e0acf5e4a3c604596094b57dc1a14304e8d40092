/**
 * Tiny holder for the post-ingest suitability Set so format.ts can do O(1)
 * lookups without importing the builder (avoids a circular dependency).
 */
let allowed: Set<string> | null = null;
let allowedSnapshot: Set<string> | null = null;
/** True while closeSuitabilityGateUntilRebuild has sealed the gate. */
let rebuildClosed = false;
let revision = 0;
const listeners = new Set<() => void>();

function setsEqual(left: Set<string> | null, right: Set<string> | null): boolean {
  if (left === null || right === null) return left === right;
  if (left.size !== right.size) return false;
  for (const value of left) {
    if (!right.has(value)) return false;
  }
  return true;
}

export function getSuitabilityAllowed(): Set<string> | null {
  return allowed;
}

export function getSuitabilityRevision(): number {
  return revision;
}

/**
 * Whether standard-only surfaces may paint filtered rates.
 * Fail-closed rebuild uses an explicit closed flag (not allowlist size) so a
 * successfully installed empty index is still ready to show the empty result.
 * `null` allowed means the index was never installed (core-only path) and is
 * ready; a warm index (empty or not) clears the closed flag on install.
 */
export function isSuitabilityFilterReady(includeNonStandard = false): boolean {
  if (includeNonStandard) return true;
  return !rebuildClosed;
}

export function subscribeSuitabilityGate(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setSuitabilityAllowed(
  next: Set<string> | null,
  opts?: { rebuildClosed?: boolean },
): void {
  const nextClosed = opts?.rebuildClosed === true;
  if (setsEqual(allowedSnapshot, next) && rebuildClosed === nextClosed) return;
  allowed = next;
  allowedSnapshot = next === null ? null : new Set(next);
  rebuildClosed = nextClosed;
  revision += 1;
  for (const listener of listeners) listener();
}
