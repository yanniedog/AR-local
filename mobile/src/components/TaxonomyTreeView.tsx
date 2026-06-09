import { Ionicons } from '@expo/vector-icons';
import { FlashList } from '@shopify/flash-list';
import React, { useCallback, useMemo, useState } from 'react';
import { Pressable, View } from 'react-native';

import { SECTIONS } from '../constants';
import { flattenTreeVisible, nodeKey, treeRootStats, type FlatTreeRow } from '../data/taxonomyTree';
import { breadcrumb } from '../data/taxonomy';
import { useStore } from '../data/store';
import { openProductsList } from '../lib/nav';
import type { SectionKey } from '../types';
import { useTheme } from '../theme/ThemeProvider';
import { EmptyState } from './feedback';
import { AppText, Row } from './ui';

const INDENT = 18;
const ROW_H = 44;

function bestRate(section: SectionKey, stats: FlatTreeRow['stats']): number | null {
  if (stats.min === null) return null;
  return SECTIONS[section].lowerIsBetter ? stats.min : stats.max;
}

function formatRate(section: SectionKey, stats: FlatTreeRow['stats']): string {
  const v = bestRate(section, stats);
  return v !== null ? `${(v * 100).toFixed(2)}%` : '—';
}

function TreeRow({
  row,
  section,
  onToggle,
  onOpenLeaf,
}: {
  row: FlatTreeRow;
  section: SectionKey;
  onToggle: (key: string) => void;
  onOpenLeaf: (path: string[]) => void;
}) {
  const theme = useTheme();
  const pad = 12 + row.depth * INDENT;
  const rateColor = SECTIONS[section].lowerIsBetter ? theme.colors.success : theme.colors.primary;

  const handlePress = () => {
    if (row.hasChildren) onToggle(row.key);
    else onOpenLeaf(row.path);
  };

  return (
    <Pressable
      onPress={handlePress}
      style={({ pressed }) => ({
        flexDirection: 'row',
        alignItems: 'center',
        minHeight: ROW_H,
        paddingLeft: pad,
        paddingRight: 12,
        borderBottomWidth: 1,
        borderBottomColor: theme.colors.border,
        backgroundColor: pressed ? theme.colors.surfaceAlt : theme.colors.bg,
      })}
      accessibilityRole="button"
      accessibilityLabel={`${row.label}, ${row.stats.products} products`}
    >
      <View style={{ width: 22, alignItems: 'center', marginRight: 4 }}>
        {row.hasChildren ? (
          <Ionicons
            name={row.expanded ? 'chevron-down' : 'chevron-forward'}
            size={16}
            color={theme.colors.textFaint}
          />
        ) : (
          <View style={{ width: 16 }} />
        )}
      </View>
      <View style={{ flex: 1, paddingRight: 8 }}>
        <AppText variant="small" weight="600" numberOfLines={1}>
          {row.label}
        </AppText>
        <AppText variant="tiny" color="textFaint" numberOfLines={1}>
          {row.stats.products} prod · {row.stats.providers} lenders · {row.stats.count} rates
        </AppText>
      </View>
      <AppText variant="small" weight="700" style={{ color: rateColor, minWidth: 52, textAlign: 'right' }}>
        {formatRate(section, row.stats)}
      </AppText>
    </Pressable>
  );
}

function expandedKeysForPath(path: string[]): Set<string> {
  const out = new Set<string>();
  for (let i = 1; i <= path.length; i++) out.add(nodeKey(path.slice(0, i)));
  return out;
}

/** Inline expandable taxonomy tree (dashboard-style paths, offline payload). */
export function TaxonomyTreeView({
  section,
  initialPath = [],
}: {
  section: SectionKey;
  initialPath?: string[];
}) {
  const theme = useTheme();
  const rows = useStore((s) => s.core?.sections[section]?.rates);
  const includeNonStandard = useStore((s) => s.prefs.includeNonStandard);
  const [expanded, setExpanded] = useState<Set<string>>(() => expandedKeysForPath(initialPath));

  const flat = useMemo(() => {
    if (!rows) return [];
    return flattenTreeVisible(rows, section, expanded, includeNonStandard);
  }, [rows, section, expanded, includeNonStandard]);

  const rootStats = useMemo(() => {
    if (!rows) return null;
    return treeRootStats(rows, section, includeNonStandard);
  }, [rows, section, includeNonStandard]);

  const focusPath = useMemo(() => {
    let deepest: string[] = [];
    for (const key of expanded) {
      const segs = key.split('.').filter(Boolean);
      if (segs.length >= deepest.length) deepest = segs;
    }
    return deepest;
  }, [expanded]);

  const crumbs = useMemo(() => breadcrumb(section, focusPath), [section, focusPath]);

  const toggle = useCallback((key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const openLeaf = useCallback(
    (path: string[]) => {
      openProductsList(section, path);
    },
    [section],
  );

  const renderItem = useCallback(
    ({ item }: { item: FlatTreeRow }) => (
      <TreeRow row={item} section={section} onToggle={toggle} onOpenLeaf={openLeaf} />
    ),
    [section, toggle, openLeaf],
  );

  if (!rows) return null;

  const header = (
    <View style={{ paddingHorizontal: 16, paddingTop: 8, paddingBottom: 6 }}>
      {focusPath.length > 0 ? (
        <AppText variant="tiny" color="textFaint" numberOfLines={2} style={{ marginBottom: 6 }}>
          {crumbs.join('  ›  ')}
        </AppText>
      ) : null}
      {rootStats ? (
        <Row style={{ justifyContent: 'space-between' }}>
          <AppText variant="tiny" color="textMuted" weight="700">
            {rootStats.products} PRODUCTS · {rootStats.providers} LENDERS
          </AppText>
          <AppText variant="tiny" weight="700" style={{ color: theme.colors.textMuted }}>
            {formatRate(section, rootStats)}
          </AppText>
        </Row>
      ) : null}
    </View>
  );

  return (
    <FlashList
      data={flat}
      keyExtractor={(item) => item.key}
      ListHeaderComponent={header}
      ListEmptyComponent={<EmptyState title="No categories" />}
      renderItem={renderItem}
    />
  );
}
