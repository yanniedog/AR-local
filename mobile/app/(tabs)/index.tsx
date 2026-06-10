import { Ionicons } from '@expo/vector-icons';
import React, { useCallback, useEffect, useMemo } from 'react';
import { Pressable, RefreshControl, View } from 'react-native';

import { BankHistoryChart } from '../../src/components/BankHistoryChart';
import { ChartErrorBoundary } from '../../src/components/ChartErrorBoundary';
import { RbaChart } from '../../src/components/charts';
import { OfflineBanner } from '../../src/components/feedback';
import { HomeHero } from '../../src/components/HomeHero';
import { ProductCard } from '../../src/components/ProductCard';
import { Ribbon } from '../../src/components/Ribbon';
import { ScreenScrollView } from '../../src/components/Screen';
import { CompactToggle, SegmentedControl } from '../../src/components/controls';
import { AppText, Card, Chip, IconButton, Row } from '../../src/components/ui';
import { SECTIONS } from '../../src/constants';
import { formatRate, formatRunDate, relativeDate } from '../../src/data/format';
import { selectBankHistoryChartModel } from '../../src/data/historySelectors';
import { resolveSectionRibbonStats } from '../../src/data/ribbonStats';
import { bestRow } from '../../src/data/selectors';
import { resolveInterestSection, sectionSegmentOptions } from '../../src/data/interests';
import { childrenOf, rowsUnder } from '../../src/data/taxonomy';
import { useStore } from '../../src/data/store';
import { openBrowseDrill, openProduct, openRibbonProducts } from '../../src/lib/nav';
import type { SectionKey } from '../../src/types';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function Home() {
  const theme = useTheme();
  const core = useStore((s) => s.core);
  const refreshing = useStore((s) => s.refreshing);
  const refresh = useStore((s) => s.refresh);
  const source = useStore((s) => s.source);
  const offline = useStore((s) => s.offline);
  const interests = useStore((s) => s.prefs.interests);
  const section = useStore((s) => s.activeSection);
  const setActiveSection = useStore((s) => s.setActiveSection);
  const includeNonStandard = useStore((s) => s.prefs.includeNonStandard);
  const showHistoryRibbon = useStore((s) => s.prefs.showHistoryRibbon);
  const historyBanks = useStore((s) => s.historyBanks);
  const historyBanksError = useStore((s) => s.historyBanksError);
  const ensureHistoryBanks = useStore((s) => s.ensureHistoryBanks);
  const setPref = useStore((s) => s.setPref);
  const sectionOptions = useMemo(() => sectionSegmentOptions(interests), [interests]);

  useEffect(() => {
    const resolved = resolveInterestSection(interests, section);
    if (resolved !== section) setActiveSection(resolved);
  }, [interests, section, setActiveSection]);

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
      contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.colors.primary} />
      }
    >
      <OfflineBanner source={source} offline={offline} />

      <Row style={{ justifyContent: 'flex-end', marginBottom: 8 }}>
        <IconButton icon="refresh" onPress={onRefresh} accessibilityLabel="Refresh" />
      </Row>

      <HomeHero
        runDateLabel={formatRunDate(core.run_date)}
        runAgeLabel={relativeDate(`${core.run_date}T00:00:00Z`)}
        source={source}
        offline={offline}
        productCount={stats.products}
        lenderCount={lenderCount}
        providerCount={stats.providers}
      />

      {sectionOptions.length > 1 ? (
        <SegmentedControl options={sectionOptions} value={section} onChange={setActiveSection} />
      ) : null}
      <View style={{ marginTop: 10 }}>
        <CompactToggle
          label="Include non-standard accounts"
          value={includeNonStandard}
          onChange={(value) => setPref('includeNonStandard', value)}
        />
      </View>

      <Card
        style={{
          marginTop: 14,
          marginBottom: 14,
          borderColor: `${accent}44`,
        }}
      >
        <Row style={{ justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
          <View style={{ flex: 1, paddingRight: 10 }}>
            <AppText variant="tiny" color="textFaint" weight="700">
              {meta.title.toUpperCase()}
            </AppText>
            <AppText variant="small" color="textMuted" style={{ marginTop: 2 }}>
              {meta.lowerIsBetter ? 'Lowest' : 'Top'} rate in section
            </AppText>
            <AppText variant="rateHero" style={{ color: accent, marginTop: 4 }}>
              {formatRate(heroRate)}
            </AppText>
          </View>
          {section === 'Mortgage' && rba ? (
            <View
              style={{
                alignItems: 'flex-end',
                backgroundColor: theme.colors.chip,
                paddingHorizontal: 10,
                paddingVertical: 8,
                borderRadius: theme.radius.md,
              }}
            >
              <AppText variant="tiny" color="textFaint">
                RBA cash
              </AppText>
              <AppText variant="rate" style={{ color: theme.colors.primary }}>
                {formatRate(rba.rate)}
              </AppText>
            </View>
          ) : null}
        </Row>
        <Ribbon stats={stats} section={section} rbaRate={section === 'Mortgage' ? rba?.rate ?? null : null} />
        <AppText variant="tiny" weight="700" color="textFaint" style={{ marginTop: 12, marginBottom: 7 }}>
          VIEW PRODUCTS
        </AppText>
        <Row gap={8} style={{ flexWrap: 'wrap' }}>
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
          <Card style={{ marginBottom: 14 }}>
            <AppText variant="h3" style={{ marginBottom: 8 }}>
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
          <Card style={{ marginBottom: 14 }}>
            <AppText variant="h3" style={{ marginBottom: 4 }}>
              {meta.title} history
            </AppText>
            <AppText variant="tiny" color="textFaint">
              History data unavailable. Showing today&apos;s ribbon only.
            </AppText>
          </Card>
        ) : null
      ) : null}

      {section === 'Mortgage' && core.rba?.length ? (
        <Card style={{ marginBottom: 14 }}>
          <Row gap={8} style={{ marginBottom: 6 }}>
            <Ionicons name="trending-up" size={16} color={theme.colors.primary} />
            <AppText variant="h3">RBA cash rate</AppText>
          </Row>
          <RbaChart data={core.rba} height={140} />
        </Card>
      ) : null}

      <AppText variant="small" weight="700" color="textMuted" style={{ marginBottom: 10, marginLeft: 2 }}>
        BROWSE BY CATEGORY
      </AppText>
      {categories.map((node) => {
        const nodeBest = meta.lowerIsBetter ? node.stats.min : node.stats.max;
        return (
          <Pressable
            key={node.seg}
            onPress={() => openBrowseDrill(section, [node.seg])}
            style={({ pressed }) => ({
              backgroundColor: theme.colors.card,
              borderRadius: theme.radius.lg,
              borderWidth: 1,
              borderColor: theme.colors.border,
              borderLeftWidth: 3,
              borderLeftColor: accent,
              padding: 14,
              marginBottom: 10,
              opacity: pressed ? 0.85 : 1,
            })}
          >
            <Row style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <View style={{ flex: 1, paddingRight: 10 }}>
                <AppText variant="body" weight="700" numberOfLines={2}>
                  {node.label}
                </AppText>
                <AppText variant="tiny" color="textFaint" style={{ marginTop: 2 }}>
                  {node.stats.products} products · {node.stats.providers} lenders
                </AppText>
              </View>
              <Row gap={4}>
                <AppText variant="rate" style={{ color: accent }}>
                  {formatRate(nodeBest)}
                </AppText>
                <Ionicons name="chevron-forward" size={18} color={theme.colors.textFaint} />
              </Row>
            </Row>
          </Pressable>
        );
      })}

      {best ? (
        <>
          <AppText variant="small" weight="700" color="textMuted" style={{ marginTop: 10, marginBottom: 10, marginLeft: 2 }}>
            BEST RATE TODAY
          </AppText>
          <ProductCard row={best} section={section} onPress={() => openProduct(best.product_key, best.rate_index)} />
        </>
      ) : null}
    </ScreenScrollView>
  );
}
