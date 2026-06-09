import { Stack, useLocalSearchParams } from 'expo-router';
import React, { useMemo } from 'react';
import { View } from 'react-native';

import { BankAvatar } from '../../src/components/BankAvatar';
import { EmptyState } from '../../src/components/feedback';
import { ProductCard } from '../../src/components/ProductCard';
import { ScreenScrollView } from '../../src/components/Screen';
import { AppText, Row } from '../../src/components/ui';
import { SECTIONS, SECTION_ORDER } from '../../src/constants';
import { sortRows } from '../../src/data/selectors';
import { useStore } from '../../src/data/store';
import { openProduct } from '../../src/lib/nav';
import type { RateRow, SectionKey } from '../../src/types';

export default function BankDetail() {
  // Already decoded by expo-router — decoding again would throw on a literal '%'.
  const { provider: raw } = useLocalSearchParams<{ provider: string }>();
  const provider = raw ?? '';
  const core = useStore((s) => s.core);

  const bySection = useMemo(() => {
    const out: { section: SectionKey; rows: RateRow[] }[] = [];
    if (!core) return out;
    for (const section of SECTION_ORDER) {
      const rows = core.sections[section]?.rates.filter((r) => r.provider === provider) ?? [];
      // De-duplicate to one card per product (lowest/best rate row).
      const byProduct = new Map<string, RateRow>();
      for (const r of sortRows(rows, 'rate', section)) {
        if (!byProduct.has(r.product_key)) byProduct.set(r.product_key, r);
      }
      if (byProduct.size) out.push({ section, rows: Array.from(byProduct.values()) });
    }
    return out;
  }, [core, provider]);

  if (!core) return null;

  return (
    <>
      <Stack.Screen options={{ title: provider }} />
      <ScreenScrollView contentContainerStyle={{ padding: 16, paddingBottom: 32 }}>
        <Row gap={14} style={{ marginBottom: 20 }}>
          <BankAvatar provider={provider} size={56} />
          <View style={{ flex: 1 }}>
            <AppText variant="h3">{provider}</AppText>
            <AppText variant="small" color="textMuted">
              {bySection.reduce((n, s) => n + s.rows.length, 0)} products
            </AppText>
          </View>
        </Row>

        {bySection.length === 0 ? (
          <EmptyState title="No products" subtitle="This lender has no rates in the current data set." />
        ) : (
          bySection.map(({ section, rows }) => (
            <View key={section} style={{ marginBottom: 12 }}>
              <AppText variant="small" weight="700" color="textMuted" style={{ marginBottom: 8, marginLeft: 4 }}>
                {SECTIONS[section].title.toUpperCase()}
              </AppText>
              {rows.map((r) => (
                <ProductCard
                  key={r.product_key}
                  row={r}
                  section={section}
                  onPress={() => openProduct(r.product_key, r.rate_index)}
                />
              ))}
            </View>
          ))
        )}
      </ScreenScrollView>
    </>
  );
}
