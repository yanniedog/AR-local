import { useScrollToTop } from '@react-navigation/native';
import { router } from 'expo-router';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, View } from 'react-native';

import { HomeHero, HomeRefreshCountdown, SpringOnNewData } from '../../src/components/HomeHero';
import { ProductCard } from '../../src/components/ProductCard';
import { RbaCountdownCard } from '../../src/components/RbaCountdownCard';
import { Ribbon } from '../../src/components/Ribbon';
import { ScreenScrollView } from '../../src/components/Screen';
import { SectionCrossfade, SegmentedControl } from '../../src/components/controls';
import { AppText, Card, Chip, Row } from '../../src/components/ui';
import { SECTIONS } from '../../src/constants';
import { formatRate, formatRunDate, relativeDate } from '../../src/data/format';
import { resolveInterestSection, sectionSegmentOptions } from '../../src/data/interests';
import { resolveSectionRibbonStats } from '../../src/data/ribbonStats';
import { profileFilterRows, profileSectionCount } from '../../src/data/profile';
import { bestRow, rankFraction } from '../../src/data/selectors';
import { conditionalNote } from '../../src/lib/rateQualifier';
import { ShareQrModal } from '../../src/components/ShareQrModal';
import { rowsUnder } from '../../src/data/taxonomy';
import { useStore } from '../../src/data/store';
import { APK_RELEASE_TAG, REPO } from '../../src/config';
import { openBank, openProduct, openRibbonProducts } from '../../src/lib/nav';
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
  const depositRankMetric = useStore((s) => s.prefs.depositRankMetric);
  const profileFilters = useStore((s) => s.prefs.profileFilters);
  const sectionOptions = useMemo(() => sectionSegmentOptions(interests), [interests]);
  const [shareOpen, setShareOpen] = useState(false);

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
  // The hero "best" honours the saved product profile (e.g. OO, P&I, your LVR).
  const profileCount = profileSectionCount(profileFilters, section);
  const best = useMemo(
    () => bestRow(profileFilterRows(hierRows, profileFilters, section), section, includeNonStandard, depositRankMetric),
    [hierRows, profileFilters, section, includeNonStandard, depositRankMetric],
  );
  const fallbackBest = useMemo(
    () => bestRow(profileFilterRows(sectionRows ?? [], profileFilters, section), section, includeNonStandard, depositRankMetric),
    [sectionRows, profileFilters, section, includeNonStandard, depositRankMetric],
  );

  const meta = SECTIONS[section];
  const shareMessage = useMemo(() => {
    if (!core) return null;
    const headline = meta.lowerIsBetter ? stats.min : stats.max;
    if (headline == null) return null; // nothing worth sharing until rates are loaded
    return [
      `Best ${meta.title.toLowerCase()} rate today: ${formatRate(headline)} (${formatRunDate(core.run_date)})`,
      `Tracked daily across ${Object.keys(core.brands ?? {}).length} Australian lenders.`,
      `Get the AustralianRates app: https://github.com/${REPO}/releases/tag/${APK_RELEASE_TAG}`,
    ].join('\n');
  }, [core, meta, stats]);
  const shareToday = useCallback(() => setShareOpen(true), []);

  if (!core) return null;
  const rba = core.rba?.at(-1);
  const sectionAccent = meta.accentColor;
  const rateInk = meta.lowerIsBetter ? theme.colors.rateLoan : theme.colors.rateDeposit;
  const activeBest = best ?? fallbackBest;
  // Show the ranked best product's own rate (base ongoing by default) so the
  // headline can't overstate what the winner actually pays; with a profile active,
  // show nothing (not the market extreme) when nothing matches.
  const heroBest = activeBest ? rankFraction(activeBest, section, depositRankMetric) : null;
  const heroRate = profileCount > 0 ? heroBest : heroBest ?? (meta.lowerIsBetter ? stats.min : stats.max);
  const bestNote = conditionalNote(activeBest, section);
  const lenderCount = Object.keys(core.brands ?? {}).length;
  const heroDataKey = `${core.run_date}:${section}:${heroRate ?? 'na'}`;
  const ribbonDataKey = `${core.run_date}:${section}:ribbon`;

  return (
    <ScreenScrollView
      ref={scrollRef}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.colors.primary} />
      }
    >
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
        onShare={shareToday}
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
              marginBottom: activeBest ? theme.spacing(3) : 0,
            }}
          >
            <View style={{ flex: 1, paddingRight: theme.spacing(3) }}>
              <AppText variant="tiny" color="textFaint" weight="700">
                BEST IN {meta.title.toUpperCase()}
              </AppText>
              <AppText variant="small" color="textMuted" style={{ marginTop: theme.spacing(1) / 2 }}>
                {meta.lowerIsBetter ? 'Lowest' : 'Top'} rate today
                {profileCount > 0 ? ' · matches your profile' : ''}
              </AppText>
              <AppText variant="rateHero" style={{ color: rateInk, marginTop: theme.spacing(1) }}>
                {formatRate(heroRate)}
              </AppText>
              {bestNote ? (
                <AppText
                  variant="tiny"
                  weight="700"
                  style={{ color: theme.colors.warning, marginTop: theme.spacing(1) }}
                >
                  {bestNote}
                </AppText>
              ) : null}
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
        {activeBest ? (
          <Pressable
            onLongPress={() => openBank(activeBest.provider)}
            delayLongPress={450}
            accessibilityHint="Long press to open lender profile"
          >
            <ProductCard
              row={activeBest}
              section={section}
              onPress={() => openProduct(activeBest.product_key, activeBest.rate_index)}
            />
          </Pressable>
        ) : null}
      </Card>
      </SectionCrossfade>

      <RbaCountdownCard />

      <AppText variant="tiny" weight="700" color="textFaint" style={{ marginBottom: theme.spacing(2) }}>
        SHORTCUTS
      </AppText>
      <Row gap={theme.spacing(2)} style={{ flexWrap: 'wrap', marginBottom: theme.spacing(5) }}>
        <Chip
          label={meta.lowerIsBetter ? 'Lowest rates' : 'Top yields'}
          icon="trending-up"
          onPress={() => openRibbonProducts(section, 'rate')}
        />
        <Chip label="Calculator" icon="calculator-outline" onPress={() => router.push('/calculator')} />
        <Chip label="My profile" icon="person-circle-outline" onPress={() => router.push('/profile')} />
        <Chip label="Why rates move" icon="pulse-outline" onPress={() => router.push('/rba')} />
        {section === 'Mortgage' ? (
          <Chip
            label="Comparison"
            icon="swap-vertical"
            onPress={() => openRibbonProducts(section, 'comparison')}
          />
        ) : null}
      </Row>

      <HomeRefreshCountdown />

      <Card>
        <AppText variant="small" weight="700" color="textMuted" style={{ marginBottom: theme.spacing(2) }}>
          {meta.title} distribution
        </AppText>
        <SpringOnNewData dataKey={ribbonDataKey}>
          <Ribbon stats={stats} section={section} rbaRate={section === 'Mortgage' ? rba?.rate ?? null : null} />
        </SpringOnNewData>
      </Card>
      <ShareQrModal visible={shareOpen} onClose={() => setShareOpen(false)} shareMessage={shareMessage} />
    </ScreenScrollView>
  );
}
