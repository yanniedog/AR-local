import { Ionicons } from '@expo/vector-icons';
import { FlashList } from '@shopify/flash-list';
import React, { useMemo } from 'react';
import { Pressable, View } from 'react-native';

import { SECTIONS } from '../constants';
import { sortRows } from '../data/selectors';
import {
  childrenOf,
  rowsUnder,
  statsFor,
  type TaxoNode,
} from '../data/taxonomy';
import { useStore } from '../data/store';
import { openNode, openProduct, openProductsList } from '../lib/nav';
import type { RateRow, SectionKey } from '../types';
import { useTheme } from '../theme/ThemeProvider';
import { ProductCard } from './ProductCard';
import { Ribbon } from './Ribbon';
import { AppText, Card, Row } from './ui';
import { EmptyState } from './feedback';

type Item = { kind: 'node'; node: TaxoNode } | { kind: 'product'; row: RateRow };

/** The dashboard-style drill-down: a ribbon for the current node, then either
 *  child category cards or — at a leaf — the actual products. */
export function HierarchyView({ section, path }: { section: SectionKey; path: string[] }) {
  const theme = useTheme();
  const rows = useStore((s) => s.core?.sections[section]?.rates);
  const rba = useStore((s) => s.core?.rba?.at(-1)?.rate ?? null);

  const { stats, children, items } = useMemo(() => {
    const all = rows ?? [];
    const nodeRows = rowsUnder(all, section, path);
    const kids = childrenOf(all, section, path);
    const data: Item[] = kids.length
      ? kids.map((node) => ({ kind: 'node', node }) as Item)
      : sortRows(nodeRows, 'rate', section).map((row) => ({ kind: 'product', row }) as Item);
    return { stats: statsFor(nodeRows), children: kids, items: data };
  }, [rows, section, path]);

  if (!rows) return null;

  const isLeaf = children.length === 0;

  const header = (
    <View>
      <Card style={{ marginBottom: 14 }}>
        <Ribbon stats={stats} section={section} rbaRate={section === 'Mortgage' ? rba : null} />
      </Card>
      <Row style={{ justifyContent: 'space-between', marginBottom: 8, paddingHorizontal: 2 }}>
        <AppText variant="small" weight="700" color="textMuted">
          {isLeaf ? `${stats.count} PRODUCTS` : 'CATEGORIES'}
        </AppText>
        {!isLeaf ? (
          <Pressable onPress={() => openProductsList(section, path)} hitSlop={8}>
            <AppText variant="small" weight="700" style={{ color: theme.colors.primary }}>
              View all {stats.count} →
            </AppText>
          </Pressable>
        ) : null}
      </Row>
    </View>
  );

  return (
    <FlashList
      data={items}
      keyExtractor={(it, i) =>
        it.kind === 'node' ? `n-${it.node.seg}` : `p-${it.row.product_key}-${it.row.rate_index ?? i}`
      }
      contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 14, paddingBottom: 32 }}
      ListHeaderComponent={header}
      ListEmptyComponent={<EmptyState title="No products here" />}
      renderItem={({ item }) =>
        item.kind === 'node' ? (
          <NodeCard section={section} path={path} node={item.node} />
        ) : (
          <ProductCard
            row={item.row}
            section={section}
            onPress={() => openProduct(item.row.product_key, item.row.rate_index)}
          />
        )
      }
    />
  );
}

function NodeCard({ section, path, node }: { section: SectionKey; path: string[]; node: TaxoNode }) {
  const theme = useTheme();
  const best = SECTIONS[section].lowerIsBetter ? node.stats.min : node.stats.max;
  return (
    <Pressable
      onPress={() => openNode(section, [...path, node.seg])}
      style={({ pressed }) => ({
        backgroundColor: theme.colors.card,
        borderRadius: theme.radius.lg,
        borderWidth: 1,
        borderColor: theme.colors.border,
        padding: 14,
        marginBottom: 10,
        opacity: pressed ? 0.85 : 1,
      })}
    >
      <Row style={{ justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <View style={{ flex: 1, paddingRight: 10 }}>
          <AppText variant="body" weight="700" numberOfLines={2}>
            {node.label}
          </AppText>
          <AppText variant="tiny" color="textFaint" style={{ marginTop: 2 }}>
            {node.stats.count} {node.stats.count === 1 ? 'product' : 'products'} · {node.stats.providers} lenders
          </AppText>
        </View>
        <Row gap={4}>
          <AppText
            variant="h3"
            weight="800"
            style={{ color: SECTIONS[section].lowerIsBetter ? theme.colors.success : theme.colors.primary }}
          >
            {best !== null ? `${(best * 100).toFixed(2)}%` : '—'}
          </AppText>
          <Ionicons name="chevron-forward" size={18} color={theme.colors.textFaint} />
        </Row>
      </Row>
      <Ribbon stats={node.stats} section={section} compact />
    </Pressable>
  );
}
