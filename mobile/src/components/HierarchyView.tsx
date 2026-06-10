import { FlashList } from '@shopify/flash-list';
import React, { useMemo } from 'react';
import { Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

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
import { CategoryRow } from './CategoryRow';
import { ProductCard } from './ProductCard';
import { Ribbon } from './Ribbon';
import { screenScrollContentStyle } from './Screen';
import { AppText, Card, Row } from './ui';
import { EmptyState } from './feedback';

type Item = { kind: 'node'; node: TaxoNode } | { kind: 'product'; row: RateRow };

export function HierarchyView({ section, path }: { section: SectionKey; path: string[] }) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
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
      const seen = new Set<string>();
      data = sortRows(nodeRows, 'rate', section)
        .filter((r) => (seen.has(r.product_key) ? false : seen.add(r.product_key)))
        .map((row) => ({ kind: 'product', row }) as Item);
    }
    return { stats, children: kids, items: data };
  }, [rows, sectionData, section, path, includeNonStandard]);

  if (!rows) return null;

  const isLeaf = children.length === 0;
  const meta = SECTIONS[section];

  const header = (
    <View>
      <Card>
        <Ribbon stats={stats} section={section} rbaRate={section === 'Mortgage' ? rba : null} />
      </Card>
      <Row style={{ justifyContent: 'space-between', paddingHorizontal: theme.spacing(1) / 2 }}>
        <AppText variant="small" weight="700" color="textMuted">
          {isLeaf ? `${stats.products} ${stats.products === 1 ? 'PRODUCT' : 'PRODUCTS'}` : 'CATEGORIES'}
        </AppText>
        {!isLeaf ? (
          <Pressable onPress={() => openProductsList(section, path)} hitSlop={theme.spacing(2)}>
            <AppText variant="small" weight="700" style={{ color: theme.colors.primary }}>
              All {stats.products} products →
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
      contentContainerStyle={screenScrollContentStyle(theme, insets.bottom)}
      ItemSeparatorComponent={() => <View style={{ height: theme.spacing(3) }} />}
      ListHeaderComponent={header}
      ListEmptyComponent={<EmptyState title="No products here" />}
      renderItem={({ item }) =>
        item.kind === 'node' ? (
          <CategoryRow
            label={item.node.label}
            productCount={item.node.stats.products}
            providerCount={item.node.stats.providers}
            rate={meta.lowerIsBetter ? item.node.stats.min : item.node.stats.max}
            section={section}
            ribbonStats={item.node.stats}
            onPress={() => openNode(section, [...path, item.node.seg])}
          />
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
