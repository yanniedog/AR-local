import { Stack, useLocalSearchParams } from 'expo-router';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { View } from 'react-native';

import { BankAvatar } from '../../src/components/BankAvatar';
import { BankHistoryChart } from '../../src/components/BankHistoryChart';
import { BankMoveRow, InsightsLockedCard } from '../../src/components/BankInsights';
import { ChartErrorBoundary } from '../../src/components/ChartErrorBoundary';
import { EmptyState } from '../../src/components/feedback';
import { ProductCard } from '../../src/components/ProductCard';
import { ProPaywall } from '../../src/components/ProPaywall';
import { ScreenScrollView } from '../../src/components/Screen';
import { SegmentedControl } from '../../src/components/controls';
import { AppText, Card, Chip, Divider, Row } from '../../src/components/ui';
import { SECTIONS, SECTION_ORDER } from '../../src/constants';
import { bankTrendChartModel, recentBankEvents } from '../../src/data/bankInsights';
import { sortRows } from '../../src/data/selectors';
import { useStore } from '../../src/data/store';
import { useProPaywall } from '../../src/hooks/useProPaywall';
import { openProduct } from '../../src/lib/nav';
import { effectiveBankInsights } from '../../src/lib/proAccess';
import type { RateRow, SectionKey } from '../../src/types';

export default function BankDetail() {
  // Already decoded by expo-router — decoding again would throw on a literal '%'.
  const { provider: raw } = useLocalSearchParams<{ provider: string }>();
  const provider = raw ?? '';
  const core = useStore((s) => s.core);
  const depositRankMetric = useStore((s) => s.prefs.depositRankMetric);
  const showBankInsights = useStore((s) => effectiveBankInsights(s.prefs));
  const bankInsights = useStore((s) => s.bankInsights);
  const ensureBankInsights = useStore((s) => s.ensureBankInsights);
  const { paywallVisible, paywallIntent, requestPro, closePaywall } = useProPaywall();
  const insightsRequestKey = useRef<string | null>(null);

  useEffect(() => {
    const key = showBankInsights ? core?.run_date ?? null : null;
    if (!key || insightsRequestKey.current === key) return;
    insightsRequestKey.current = key;
    void ensureBankInsights();
  }, [core?.run_date, ensureBankInsights, showBankInsights]);

  const bySection = useMemo(() => {
    const out: { section: SectionKey; rows: RateRow[] }[] = [];
    if (!core) return out;
    for (const section of SECTION_ORDER) {
      const rows = core.sections[section]?.rates.filter((r) => r.provider === provider) ?? [];
      // De-duplicate to one card per product (best rate row under the ranking metric).
      const byProduct = new Map<string, RateRow>();
      for (const r of sortRows(rows, 'rate', section, depositRankMetric)) {
        if (!byProduct.has(r.product_key)) byProduct.set(r.product_key, r);
      }
      if (byProduct.size) out.push({ section, rows: Array.from(byProduct.values()) });
    }
    return out;
  }, [core, provider, depositRankMetric]);

  const chartSections = useMemo(
    () =>
      SECTION_ORDER.filter((section) => !!bankInsights?.banks?.[provider]?.[section]),
    [bankInsights, provider],
  );
  const [chartSection, setChartSection] = useState<SectionKey | null>(null);
  const activeChartSection =
    chartSection && chartSections.includes(chartSection) ? chartSection : chartSections[0] ?? null;

  const chartModel = useMemo(
    () =>
      activeChartSection
        ? bankTrendChartModel(bankInsights, provider, activeChartSection)
        : null,
    [activeChartSection, bankInsights, provider],
  );
  const bankEvents = useMemo(
    () => recentBankEvents(bankInsights, { provider, limit: 6 }),
    [bankInsights, provider],
  );

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

        {showBankInsights ? (
          chartModel && activeChartSection ? (
            <Card style={{ marginBottom: 16 }}>
              <Row style={{ justifyContent: 'space-between', marginBottom: 10 }}>
                <AppText variant="h3">Rate history</AppText>
                <Chip label="PRO" selected />
              </Row>
              {chartSections.length > 1 ? (
                <SegmentedControl
                  options={chartSections.map((s) => ({ value: s, label: SECTIONS[s].short }))}
                  value={activeChartSection}
                  onChange={setChartSection}
                />
              ) : null}
              <AppText variant="tiny" color="textFaint" style={{ marginTop: 6, marginBottom: 4 }}>
                Band spans this lender's sharpest offer to its typical rate
              </AppText>
              <ChartErrorBoundary name="BankTrendChart">
                <BankHistoryChart
                  dates={chartModel.dates}
                  points={chartModel.points}
                  allDates={chartModel.allDates}
                  rba={core.rba}
                  rbaHolds={core.rba_holds}
                  section={activeChartSection}
                  height={200}
                />
              </ChartErrorBoundary>
              {bankEvents.length ? (
                <>
                  <Divider style={{ marginVertical: 10 }} />
                  <AppText variant="small" weight="700" style={{ marginBottom: 2 }}>
                    Recent moves
                  </AppText>
                  {bankEvents.map((event) => (
                    <BankMoveRow key={`${event.date}-${event.section}`} event={event} />
                  ))}
                </>
              ) : null}
            </Card>
          ) : null
        ) : (
          <Card style={{ marginBottom: 16 }}>
            <InsightsLockedCard onUnlock={() => requestPro('bank_insights')} />
          </Card>
        )}

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
        <ProPaywall visible={paywallVisible} intent={paywallIntent} onClose={closePaywall} />
      </ScreenScrollView>
    </>
  );
}
