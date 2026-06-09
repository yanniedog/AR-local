import { Ionicons } from '@expo/vector-icons';
import { FlashList } from '@shopify/flash-list';
import React, { useMemo } from 'react';
import { Pressable, View } from 'react-native';

import { SECTIONS } from '../constants';
import { visibleAccountRows } from '../data/format';
import { resolveSectionRibbonStats } from '../data/ribbonStats';
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
 *  child category cards or ??? at a leaf ??? the actual products. */
export function HierarchyView({ section, path }: { section: SectionKey; path: string[] }) {
  const theme = useTheme();
  const sectionData = useStore((s) => s.core?.sections[section]);
  const rows = sectionData?.rates;
  const rba = useStore((s) => s.core?.rba?.at(-1)?.rate ?? null);
  const includeNonStandard = useStore((s) => s.prefs.includeNonStandard);

  const { stats, children, items } = useMemo(() => {
    const all = rows ?? [];
    const nodeRows = visibleAccountRows(rowsUnder(all, section, path), includeNonStandard);
    const kids = childrenOf(all, section, path, includeNonStandard);
    const stats =
      path.length === 0
        ? resolveSectionRibbonStats(sectionData, rowsUnder(all, section, path), includeNonStandard)
        : statsFor(nodeRows, true);
    let data: Item[];
    if (kids.length) {
      data = kids.map((node) => ({ kind: 'node', node }) as Item);
    } else {
      // Leaf: show one card per distinct product (best rate row), so the list
      // matches the product count instead of repeating a product across rate rows.
      const seen = new Set<string>();
      data = sortRows(nodeRows, 'rate', section)
        .filter((r) => (seen.has(r.product_key) ? false : seen.add(r.product_key)))
        .map((row) => ({ kind: 'product', row }) as Item);
    }
    return { stats, children: kids, items: data };
  }, [rows, sectionData, section, path, includeNonStandard]);

  if (!rows) return null;

  const isLeaf = children.length === 0;

  const header = (
    <View>
      <Card style={{ marginBottom: 14 }}>
        <Ribbon stats={stats} section={section} rbaRate={section === 'Mortgage' ? rba : null} />
      </Card>
      <Row style={{ justifyContent: 'space-between', marginBottom: 8, paddingHorizontal: 2 }}>
        <AppText variant="small" weight="700" color="textMuted">
          {isLeaf ? `${stats.products} ${stats.products === 1 ? 'PRODUCT' : 'PRODUCTS'}` : 'CATEGORIES'}
        </AppText>
        {!isLeaf ? (
          <Pressable onPress={() => openProductsList(section, path)} hitSlop={8}>
            <AppText variant="small" weight="700" style={{ color: theme.colors.primary }}>
              All {stats.products} products ???
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
            {node.stats.products} {node.stats.products === 1 ? 'product' : 'products'} ?? {node.stats.providers} lenders
          </AppText>
        </View>
        <Row gap={4}>
          <AppText
            variant="h3"
            weight="800"
            style={{ color: SECTIONS[section].lowerIsBetter ? theme.colors.success : theme.colors.primary }}
          >
            {best !== null ? `${(best * 100).toFixed(2)}%` : '???'}
          </AppText>
          <Ionicons name="chevron-forward" size={18} color={theme.colors.textFaint} />
        </Row>
      </Row>
      <Ribbon stats={node.stats} section={section} compact />
    </Pressable>
  );
}
