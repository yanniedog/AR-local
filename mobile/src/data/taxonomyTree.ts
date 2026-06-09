import type { RateRow, SectionKey } from '../types';
import { visibleAccountRows } from './format';
import { childrenOf, rowsUnder, statsFor, type RateStats } from './taxonomy';

/** Stable key for a taxonomy path relative to the section root (excludes HOME_LOAN etc.). */
export function nodeKey(path: readonly string[]): string {
  return path.join('.');
}

export interface FlatTreeRow {
  key: string;
  depth: number;
  path: string[];
  seg: string;
  label: string;
  stats: RateStats;
  hasChildren: boolean;
  expanded: boolean;
}

/** Depth-first flatten of visible tree rows given an expanded-key set. */
export function flattenTreeVisible(
  rows: RateRow[],
  section: SectionKey,
  expandedKeys: ReadonlySet<string>,
  includeNonStandard = false,
): FlatTreeRow[] {
  const out: FlatTreeRow[] = [];
  const walk = (path: string[], depth: number) => {
    for (const node of childrenOf(rows, section, path, includeNonStandard)) {
      const nodePath = [...path, node.seg];
      const key = nodeKey(nodePath);
      const expanded = expandedKeys.has(key);
      out.push({
        key,
        depth,
        path: nodePath,
        seg: node.seg,
        label: node.label,
        stats: node.stats,
        hasChildren: node.hasChildren,
        expanded,
      });
      if (node.hasChildren && expanded) {
        walk(nodePath, depth + 1);
      }
    }
  };
  walk([], 0);
  return out;
}

/** Aggregate stats for all rows under a section root (tree header). */
export function treeRootStats(
  rows: RateRow[],
  section: SectionKey,
  includeNonStandard = false,
): RateStats {
  const scoped = visibleAccountRows(rowsUnder(rows, section, []), includeNonStandard);
  return statsFor(scoped, true);
}

/** Child segment keys one level below `path` (for tests and expand-all helpers). */
export function childKeysAt(
  rows: RateRow[],
  section: SectionKey,
  path: string[],
  includeNonStandard = false,
): string[] {
  return childrenOf(rows, section, path, includeNonStandard).map((n) => n.seg);
}
