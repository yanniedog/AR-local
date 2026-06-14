function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function finiteCoord(value: number): number | null {
  return Number.isFinite(value) ? value : null;
}

function joinLineTo(points: string[]): string {
  return points.length ? ` L ${points.join(' L ')}` : '';
}

/** Open line path; optionally restart after null/invalid values instead of bridging gaps. */
export function buildLinePath(
  values: (number | null)[],
  xAt: (i: number) => number,
  yAt: (v: number) => number,
  breakOnGaps = false,
): string | null {
  let d = '';
  let started = false;
  for (let i = 0; i < values.length; i += 1) {
    const value = values[i];
    if (!isFiniteNumber(value)) {
      if (breakOnGaps) started = false;
      continue;
    }
    const x = finiteCoord(xAt(i));
    const y = finiteCoord(yAt(value));
    if (x == null || y == null) {
      if (breakOnGaps) started = false;
      continue;
    }
    const segment = `${started ? 'L' : 'M'} ${x} ${y}`;
    d += started || d ? ` ${segment}` : segment;
    started = true;
  }
  return d || null;
}

/** Closed min/max ribbon path for react-native-svg `<Path d={...} />`. */
export function buildBandPath(
  dates: string[],
  mins: (number | null)[],
  maxs: (number | null)[],
  xAt: (i: number) => number,
  yAt: (v: number) => number,
): string | null {
  const upper: string[] = [];
  const lower: string[] = [];
  for (let i = 0; i < dates.length; i += 1) {
    const min = mins[i];
    const max = maxs[i];
    if (!isFiniteNumber(min) || !isFiniteNumber(max)) continue;
    const x = finiteCoord(xAt(i));
    const yMin = finiteCoord(yAt(min));
    const yMax = finiteCoord(yAt(max));
    if (x == null || yMin == null || yMax == null) continue;
    upper.push(`${x},${yMax}`);
    lower.unshift(`${x},${yMin}`);
  }
  if (!upper.length || !lower.length) return null;
  if (upper.length === 1) {
    return `M ${upper[0]} L ${lower[0]} Z`;
  }
  return `M ${upper[0]}${joinLineTo(upper.slice(1))}${joinLineTo(lower)} Z`;
}
