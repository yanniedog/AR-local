import { Ionicons } from '@expo/vector-icons';
import { useScrollToTop } from '@react-navigation/native';
import { router } from 'expo-router';
import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import { Pressable, RefreshControl, ScrollView, View } from 'react-native';

import { CategoryRow } from '../../src/components/CategoryRow';
import { HomeHero, HomeRefreshCountdown, SpringOnNewData } from '../../src/components/HomeHero';
import { ProductCard } from '../../src/components/ProductCard';
import { Ribbon } from '../../src/components/Ribbon';
import { ScreenScrollView } from '../../src/components/Screen';
import { SectionCrossfade, SegmentedControl } from '../../src/components/controls';
import { AppText, Card, Chip, IconButton, Row } from '../../src/components/ui';
import { SECTIONS } from '../../src/constants';
import { formatRate, formatRunDate, relativeDate } from '../../src/data/format';
import { marketPulse } from '../../src/data/bankInsights';
import { resolveInterestSection, sectionSegmentOptions } from '../../src/data/interests';
import { resolveSectionRibbonStats } from '../../src/data/ribbonStats';
import { bestRow } from '../../src/data/selectors';
import { childrenOf, rowsUnder } from '../../src/data/taxonomy';
import { useStore } from '../../src/data/store';
import { effectiveBankInsights, effectiveHistoryRibbon } from '../../src/lib/proAccess';
import { logCategoryRowPress } from '../../src/lib/degradationLog';
import { openBank, openNode, openProduct, openRibbonProducts } from '../../src/lib/nav';
import type { SectionKey } from '../../src/types';
import { useTheme } from '../../src/theme/ThemeProvider';

function openTrendsTab() {
  router.push('/(tabs)/trends');
}

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
  const showHistoryRibbon = useStore((s) => effectiveHistoryRibbon(s.prefs));
  const showBankInsights = useStore((s) => effectiveBankInsights(s.prefs));
  const bankInsights = useStore((s) => s.bankInsights);
  const sectionOptions = useMemo(() => sectionSegmentOptions(interests), [interests]);
  const pulse = useMemo(
    () => (showBankInsights ? marketPulse(bankInsights, 7) : null),
    [bankInsights, showBankInsights],
  );

  useEffect(() => {
    const resolved = resolveInterestSection(interests, section);
    if (resolved !== section) setActiveSection(resolved);
  }, [interests, section, setActiveSection]);

  const onRefresh = useCallback(() => void refresh({ manual: true, force: true }), [refresh]);
  const scrollRef = useRef<ScrollView>(null);
  useScrollToTop(scrollRef);

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

  if (!core) return null;
  const meta = SECTIONS[section];
  const rba = core.rba?.at(-1);
  const sectionAccent = meta.accentColor;
  const rateInk = meta.lowerIsBetter ? theme.colors.rateLoan : theme.colors.rateDeposit;
  const heroRate = meta.lowerIsBetter ? stats.min : stats.max;
  const lenderCount = Object.keys(core.brands ?? {}).length;
  const trendsDetail = pulse?.banksMoved
    ? `${pulse.banksMoved} bank${pulse.banksMoved === 1 ? '' : 's'} moved rates this week — see who cut and who hiked`
    : showBankInsights
      ? 'Bank moves feed, RBA pass-through, market history'
      : showHistoryRibbon
        ? `${meta.title} history ribbon, RBA cash rate, market snapshot`
        : 'Bank moves, RBA pass-through & rate history — Pro';
  const heroDataKey = `${core.run_date}:${section}:${heroRate ?? 'na'}`;
  const ribbonDataKey = `${core.run_date}:${section}:ribbon`;

  return (
    <ScreenScrollView
      ref={scrollRef}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.colors.primary} />
      }
    >
      <Row style={{ justifyContent: 'flex-end', marginBottom: 8 }}>
        <IconButton
          icon="refresh"
          onPress={onRefresh}
          disabled={refreshing}
          accessibilityLabel="Refresh"
        />
      </Row>

      <HomeHero
        dataKey={core.run_date}
        runDateLabel={formatRunDate(core.run_date)}
        runAgeLabel={relativeDate(`${core.run_date}T00:00:00Z`)}
        source={source}
        offline={offline}
        productCount={stats.products}
        lenderCount={lenderCount}
        providerCount={stats.providers}
        onLendersPress={() => router.push('/banks')}
      />

      {sectionOptions.length > 1 ? (
        <SegmentedControl options={sectionOptions} value={section} onChange={setActiveSection} />
      ) : null}

      <SectionCrossfade section={section}>
      <Card style={{ borderColor: `${sectionAccent}44` }}>
        <SpringOnNewData dataKey={heroDataKey}>
          <Row
            style={{
              justifyContent: 'space-between',
              alignItems: 'flex-start',
              marginBottom: best ? theme.spacing(3) : 0,
            }}
          >
            <View style={{ flex: 1, paddingRight: theme.spacing(3) }}>
              <AppText variant="tiny" color="textFaint" weight="700">
                BEST IN {meta.title.toUpperCase()}
              </AppText>
              <AppText variant="small" color="textMuted" style={{ marginTop: theme.spacing(1) / 2 }}>
                {meta.lowerIsBetter ? 'Lowest' : 'Top'} rate today
              </AppText>
              <AppText variant="rateHero" style={{ color: rateInk, marginTop: theme.spacing(1) }}>
                {formatRate(heroRate)}
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
                <AppText variant="rate" style={{ color: theme.colors.rba }}>
                  {formatRate(rba.rate)}
                </AppText>
              </View>
            ) : null}
          </Row>
        </SpringOnNewData>
        {best ? (
          <Pressable
            onLongPress={() => openBank(best.provider)}
            delayLongPress={450}
            accessibilityHint="Long press to open lender profile"
          >
            <ProductCard row={best} section={section} onPress={() => openProduct(best.product_key, best.rate_index)} />
          </Pressable>
        ) : null}
      </Card>
      </SectionCrossfade>

      <AppText variant="tiny" weight="700" color="textFaint" style={{ marginBottom: theme.spacing(2) }}>
        SHORTCUTS
      </AppText>
      <Row gap={theme.spacing(2)} style={{ flexWrap: 'wrap', marginBottom: theme.spacing(5) }}>
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

      <AppText variant="small" weight="700" color="textMuted">
        MORE
      </AppText>

      <Pressable
        onPress={openTrendsTab}
        accessibilityRole="button"
        accessibilityLabel={`Open ${meta.title} charts and trends`}
        style={({ pressed }) => ({ marginBottom: theme.spacing(3), opacity: pressed ? 0.85 : 1 })}
      >
        <Card>
          <Row style={{ alignItems: 'center' }}>
            <View
              style={{
                width: 40,
                height: 40,
                borderRadius: theme.radius.sm,
                backgroundColor: theme.colors.chip,
                alignItems: 'center',
                justifyContent: 'center',
                marginRight: theme.spacing(3),
              }}
            >
              <Ionicons name="stats-chart" size={20} color={sectionAccent} />
            </View>
            <View style={{ flex: 1, paddingRight: theme.spacing(2) }}>
              <AppText variant="body" weight="700">
                {showBankInsights ? 'Bank intelligence & trends' : 'Charts & trends'}
              </AppText>
              <AppText variant="tiny" color="textMuted" style={{ marginTop: theme.spacing(1) / 2 }}>
                {trendsDetail}
              </AppText>
            </View>
            <Ionicons name="chevron-forward" size={18} color={theme.colors.textFaint} />
          </Row>
        </Card>
      </Pressable>

      <HomeRefreshCountdown />

      <Card>
        <AppText variant="small" weight="700" color="textMuted" style={{ marginBottom: theme.spacing(2) }}>
          {meta.title} distribution
        </AppText>
        <SpringOnNewData dataKey={ribbonDataKey}>
          <Ribbon stats={stats} section={section} rbaRate={section === 'Mortgage' ? rba?.rate ?? null : null} />
        </SpringOnNewData>
      </Card>

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
          accent={sectionAccent}
          showAccent
          onPress={() => { const nextPath = [node.seg]; logCategoryRowPress({ section, label: node.label, pathBefore: [], pathAfter: nextPath, source: 'home' }); openNode(section, nextPath); }}
        />
      ))}
    </ScreenScrollView>
  );
}
