export function dateIndex<T>(values: T[], date: (value: T) => string): Map<string, T[]> {
  const result = new Map<string, T[]>();
  for (const value of values) { const key = date(value), list = result.get(key) ?? []; list.push(value); result.set(key, list); }
  return result;
}
