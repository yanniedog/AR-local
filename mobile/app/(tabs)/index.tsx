import { Ionicons } from '@expo/vector-icons';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshControl, View } from 'react-native';

import { BankHistoryChart } from '../../src/components/BankHistoryChart';
import { CategoryRow } from '../../src/components/CategoryRow';
import { ChartErrorBoundary } from '../../src/components/ChartErrorBoundary';
import { RbaChart } from '../../src/components/charts';
import { OfflineBanner } from '../../src/components/feedback';
import { HomeHero } from '../../src/components/HomeHero';
import { ProductCard } from '../../src/components/ProductCard';
import { Ribbon } from '../../src/components/Ribbon';
import { ScreenScrollView } from '../../src/components/Screen';
import { CompactToggle, SegmentedControl } from '../../src/components/controls';
import { AppText, Card, Chip, Row } from '../../src/components/ui';
import { SECTIONS } from '../../src/constants';
import { formatRunDate, relativeDate } from '../../src/data/format';
import { selectBankHistoryChartModel } from '../../src/data/historySelectors';
import { resolveSectionRibbonStats } from '../../src/data/ribbonStats';
import { bestRow } from '../../src/data/selectors';
import { childrenOf, rowsUnder } from '../../src/data/taxonomy';
import { useStore } from '../../src/data/store';
import { openNode, openProduct, openRibbonProducts } from '../../src/lib/nav';
import type { SectionKey } from '../../src/types';
import { useTheme } from '../../src/theme/ThemeProvider';

const SECTION_SEG = [
  { value: 'Mortgage' as SectionKey, label: 'Loans' },
  { value: 'Savings' as SectionKey, label: 'Savings' },
  { value: 'TD' as SectionKey, label: 'Deposits' },
];

export default function Home() {
  const theme = useTheme();
  const core = useStore((s) => s.core);
  const refreshing = useStore((s) => s.refreshing);
  const refresh = useStore((s) => s.refresh);
  const source = useStore((s) => s.source);
  const offline = useStore((s) => s.offline);
  const defaultSection = useStore((s) => s.prefs.defaultSection);
  const includeNonStandard = useStore((s) => s.prefs.includeNonStandard);
  const showHistoryRibbon = useStore((s) => s.prefs.showHistoryRibbon);
  const historyBanks = useStore((s) => s.historyBanks);
  const historyBanksError = useStore((s) => s.historyBanksError);
  const ensureHistoryBanks = useStore((s) => s.ensureHistoryBanks);
  const setPref = useStore((s) => s.setPref);
  const [section, setSection] = useState<SectionKey>(defaultSection);

  useEffect(() => {
    if (showHistoryRibbon) void ensureHistoryBanks();
  }, [showHistoryRibbon, ensureHistoryBanks]);

  const onRefresh = useCallback(() => void refresh({ manual: true, force: true }), [refresh]);

  const sectionRows = core?.sections[section]?.rates;
  const sectionData = core?.sections[section];
  const hierRows = useMemo(() => rowsUnder(sectionRows ?? [], section, []), [sectionRows, section]);
  const stats = useMemo(
    () => resolveSectionRibbonStats(sectionData, hierRows, includeNonStandard),
    [sectionData, hierRows, includeNonStandard],
  );
  const categories = useMemo(
    () => childrenOf(hierRows, section, [], includeNonStandard),
    [hierRows, section, includeNonStandard],
  );
  const best = useMemo(
    () => bestRow(hierRows, section, includeNonStandard),
    [hierRows, section, includeNonStandard],
  );
  const historyModel = useMemo(
    () =>
      showHistoryRibbon && core
        ? selectBankHistoryChartModel({ core, historyBanks, includeNonStandard }, section)
        : null,
    [showHistoryRibbon, core, historyBanks, includeNonStandard, section],
  );

  if (!core) return null;
  const meta = SECTIONS[section];
  const rba = core.rba?.at(-1);
  const accent = meta.lowerIsBetter ? theme.colors.success : theme.colors.primary;
  const heroRate = meta.lowerIsBetter ? stats.min : stats.max;
  const lenderCount = Object.keys(core.brands ?? {}).length;

  return (
    <ScreenScrollView
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.colors.primary} />
      }
    >
      <OfflineBanner source={source} offline={offline} />

      <HomeHero
        runDateLabel={formatRunDate(core.run_date)}
        runAgeLabel={relativeDate(`${core.run_date}T00:00:00Z`)}
        source={source}
        offline={offline}
        productCount={stats.products}
        lenderCount={lenderCount}
        providerCount={stats.providers}
      />

      <SegmentedControl options={SECTION_SEG} value={section} onChange={setSection} />
      <CompactToggle
        label="Include non-standard accounts"
        value={includeNonStandard}
        onChange={(value) => setPref('includeNonStandard', value)}
      />

      <Card style={{ borderColor: `${accent}44` }}>
        <Row style={{ justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: theme.spacing(3) }}>
          <View style={{ flex: 1, paddingRight: theme.spacing(3) }}>
            <AppText variant="tiny" color="textFaint" weight="700">
              {meta.title.toUpperCase()}
            </AppText>
            <AppText variant="small" color="textMuted" style={{ marginTop: theme.spacing(1) / 2 }}>
              {meta.lowerIsBetter ? 'Lowest' : 'Top'} rate in section
            </AppText>
            <AppText variant="h1" weight="800" style={{ color: accent, marginTop: theme.spacing(1) }}>
              {heroRate !== null ? `${(heroRate * 100).toFixed(2)}%` : '—'}
            </AppText>
          </View>
          {section === 'Mortgage' && rba ? (
            <View
              style={{
                alignItems: 'flex-end',
                backgroundColor: theme.colors.chip,
                paddingHorizontal: theme.spacing(3),
                paddingVertical: theme.spacing(2),
                borderRadius: theme.radius.md,
              }}
            >
              <AppText variant="tiny" color="textFaint">
                RBA cash
              </AppText>
              <AppText variant="h3" weight="800" style={{ color: theme.colors.primary }}>
                {rba.rate.toFixed(2)}%
              </AppText>
            </View>
          ) : null}
        </Row>
        <Ribbon stats={stats} section={section} rbaRate={section === 'Mortgage' ? rba?.rate ?? null : null} />
        <AppText variant="tiny" weight="700" color="textFaint" style={{ marginTop: theme.spacing(3), marginBottom: theme.spacing(2) }}>
          VIEW PRODUCTS
        </AppText>
        <Row gap={theme.spacing(2)} style={{ flexWrap: 'wrap' }}>
          <Chip
            label={meta.lowerIsBetter ? 'Lowest rates' : 'Top yields'}
            icon="trending-up"
            onPress={() => openRibbonProducts(section, 'rate')}
          />
          {section === 'Mortgage' ? (
            <Chip
              label="Comparison"
              icon="swap-vertical"
              onPress={() => openRibbonProducts(section, 'comparison')}
            />
          ) : null}
          <Chip label="Bank A-Z" icon="business" onPress={() => openRibbonProducts(section, 'bank')} />
        </Row>
      </Card>

      {showHistoryRibbon ? (
        historyModel ? (
          <Card>
            <AppText variant="h3" style={{ marginBottom: theme.spacing(2) }}>
              {meta.title} history
            </AppText>
            <ChartErrorBoundary name="BankHistoryChart">
              <BankHistoryChart
                dates={historyModel.dates}
                points={historyModel.points}
                allDates={historyModel.allDates}
                rba={section === 'Mortgage' ? core.rba : undefined}
                section={section}
              />
            </ChartErrorBoundary>
          </Card>
        ) : historyBanksError ? (
          <Card>
            <AppText variant="h3" style={{ marginBottom: theme.spacing(1) }}>
              {meta.title} history
            </AppText>
            <AppText variant="tiny" color="textFaint">
              History data unavailable. Showing today&apos;s ribbon only.
            </AppText>
          </Card>
        ) : null
      ) : null}

      {section === 'Mortgage' && core.rba?.length ? (
        <Card>
          <Row gap={theme.spacing(2)} style={{ marginBottom: theme.spacing(2) }}>
            <Ionicons name="trending-up" size={16} color={theme.colors.primary} />
            <AppText variant="h3">RBA cash rate</AppText>
          </Row>
          <RbaChart data={core.rba} height={140} />
        </Card>
      ) : null}

      <AppText variant="small" weight="700" color="textMuted">
        BROWSE BY CATEGORY
      </AppText>
      {categories.map((node) => (
        <CategoryRow
          key={node.seg}
          label={node.label}
          productCount={node.stats.products}
          providerCount={node.stats.providers}
          rate={meta.lowerIsBetter ? node.stats.min : node.stats.max}
          section={section}
          accent={accent}
          showAccent
          onPress={() => openNode(section, [node.seg])}
        />
      ))}

      {best ? (
        <>
          <AppText variant="small" weight="700" color="textMuted">
            BEST RATE TODAY
          </AppText>
          <ProductCard row={best} section={section} onPress={() => openProduct(best.product_key, best.rate_index)} />
        </>
      ) : null}
    </ScreenScrollView>
  );
}
