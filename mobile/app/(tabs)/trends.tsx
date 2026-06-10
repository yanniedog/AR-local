import { Ionicons } from '@expo/vector-icons';
import { useScrollToTop } from '@react-navigation/native';
import { router } from 'expo-router';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { BankHistoryChart } from '../../src/components/BankHistoryChart';
import {
  BankMovesFeed,
  InsightsLockedCard,
  MarketPulseStrip,
  MoversLeaderboard,
  RbaPassThroughCard,
} from '../../src/components/BankInsights';
import { ChartErrorBoundary } from '../../src/components/ChartErrorBoundary';
import { ProPaywall } from '../../src/components/ProPaywall';
import { RbaChart } from '../../src/components/charts';
import { Ribbon } from '../../src/components/Ribbon';
import { ScreenScrollView } from '../../src/components/Screen';
import { SegmentedControl } from '../../src/components/controls';
import { AppText, Button, Card, Chip, Divider, Row } from '../../src/components/ui';
import { SECTIONS } from '../../src/constants';
import { formatRate, formatRunDate } from '../../src/data/format';
import { selectBankHistoryChartModel } from '../../src/data/historySelectors';
import { orderedInterestSections, sectionSegmentOptions } from '../../src/data/interests';
import { resolveSectionRibbonStats } from '../../src/data/ribbonStats';
import { bestRow } from '../../src/data/selectors';
import { useStore } from '../../src/data/store';
import { useProPaywall } from '../../src/hooks/useProPaywall';
import { rateValueLabel, rbaDecisionA11yLabel } from '../../src/lib/a11ySummaries';
import { runStoreRetry } from '../../src/lib/degradationLog';
import { openBrowse } from '../../src/lib/nav';
import { effectiveBankInsights, effectiveHistoryRibbon } from '../../src/lib/proAccess';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function Trends() {
  const theme = useTheme();
  const core = useStore((s) => s.core);
  const interests = useStore((s) => s.prefs.interests);
  const includeNonStandard = useStore((s) => s.prefs.includeNonStandard);
  const showHistoryRibbon = useStore((s) => effectiveHistoryRibbon(s.prefs));
  const showBankInsights = useStore((s) => effectiveBankInsights(s.prefs));
  const historyBanks = useStore((s) => s.historyBanks);
  const historyBanksError = useStore((s) => s.historyBanksError);
  const ensureHistoryBanks = useStore((s) => s.ensureHistoryBanks);
  const retryHistoryBanks = useStore((s) => s.retryHistoryBanks);
  const bankInsights = useStore((s) => s.bankInsights);
  const bankInsightsError = useStore((s) => s.bankInsightsError);
  const ensureBankInsights = useStore((s) => s.ensureBankInsights);
  const retryBankInsights = useStore((s) => s.retryBankInsights);
  const activeSection = useStore((s) => s.activeSection);
  const setActiveSection = useStore((s) => s.setActiveSection);
  const { paywallVisible, paywallIntent, requestPro, closePaywall } = useProPaywall();
  const historyRequestKey = useRef<string | null>(null);
  const insightsRequestKey = useRef<string | null>(null);
  const scrollRef = useRef<ScrollView>(null);
  useScrollToTop(scrollRef);
  const [retryingInsights, setRetryingInsights] = useState(false);
  const [retryingHistory, setRetryingHistory] = useState(false);

  const handleRetryInsights = async () => {
    setRetryingInsights(true);
    try {
      await runStoreRetry(
        'retryBankInsights',
        () => retryBankInsights(),
        () => !!useStore.getState().bankInsights,
        () => useStore.getState().bankInsightsError,
      );
    } finally {
      setRetryingInsights(false);
    }
  };

  const handleRetryHistory = async () => {
    setRetryingHistory(true);
    try {
      await runStoreRetry(
        'retryHistoryBanks',
        () => retryHistoryBanks(),
        () => !!useStore.getState().historyBanks && !useStore.getState().historyBanksError,
        () => useStore.getState().historyBanksError,
      );
    } finally {
      setRetryingHistory(false);
    }
  };

  const interestSections = useMemo(() => orderedInterestSections(interests), [interests]);
  const sectionOptions = useMemo(() => sectionSegmentOptions(interests), [interests]);
  const historyModel = useMemo(
    () =>
      core
        ? selectBankHistoryChartModel(
            { core, historyBanks, includeNonStandard },
            activeSection,
            'All',
          )
        : null,
    [activeSection, core, historyBanks, includeNonStandard],
  );

  useEffect(() => {
    const key = showHistoryRibbon ? core?.run_date ?? null : null;
    if (!key || historyRequestKey.current === key) return;
    historyRequestKey.current = key;
    void ensureHistoryBanks();
  }, [core?.run_date, ensureHistoryBanks, showHistoryRibbon]);

  useEffect(() => {
    const key = showBankInsights ? core?.run_date ?? null : null;
    if (!key || insightsRequestKey.current === key) return;
    insightsRequestKey.current = key;
    void ensureBankInsights();
  }, [core?.run_date, ensureBankInsights, showBankInsights]);

  const decisions = useMemo(() => {
    if (!core) return [];
    const out: { date: string; rate: number; prior: number }[] = [];
    for (let i = 1; i < core.rba.length; i++) {
      if (core.rba[i].rate !== core.rba[i - 1].rate) {
        out.push({ date: core.rba[i].date, rate: core.rba[i].rate, prior: core.rba[i - 1].rate });
      }
    }
    return out.reverse().slice(0, 8);
  }, [core]);

  if (!core) return null;
  const currentRba = core.rba.at(-1);

  return (
    <ScreenScrollView ref={scrollRef} contentContainerStyle={{ padding: 16, paddingBottom: 32 }}>
      {showBankInsights ? (
        <>
          {bankInsights ? (
            <View style={{ marginBottom: 12 }}>
              <MarketPulseStrip payload={bankInsights} />
            </View>
          ) : null}
          <Card style={{ marginBottom: 16 }}>
            <Row style={{ justifyContent: 'space-between', marginBottom: 6 }}>
              <AppText variant="h3">Bank moves</AppText>
              <Chip label="PRO" selected />
            </Row>
            <AppText variant="tiny" color="textFaint" style={{ marginBottom: 4 }}>
              Detected daily from every lender's advertised rates
            </AppText>
            <BankMovesFeed payload={bankInsights} error={bankInsightsError} limit={8} />
            {bankInsightsError && !bankInsights ? (
              <Row style={{ justifyContent: 'space-between', marginTop: 8 }}>
                <AppText variant="tiny" color="danger" style={{ flex: 1 }}>
                  {bankInsightsError}
                </AppText>
                <Button
                  title="Retry"
                  variant="ghost"
                  onPress={handleRetryInsights}
                  loading={retryingInsights}
                  disabled={retryingInsights}
                />
              </Row>
            ) : null}
          </Card>
          {bankInsights ? (
            <Card style={{ marginBottom: 16 }}>
              <AppText variant="h3" style={{ marginBottom: 10 }}>
                Movers
              </AppText>
              {sectionOptions.length > 1 ? (
                <SegmentedControl
                  options={sectionOptions}
                  value={activeSection}
                  onChange={setActiveSection}
                />
              ) : null}
              <View style={{ marginTop: 8 }}>
                <MoversLeaderboard payload={bankInsights} section={activeSection} />
              </View>
            </Card>
          ) : null}
        </>
      ) : (
        <Card style={{ marginBottom: 16 }}>
          <InsightsLockedCard onUnlock={() => requestPro('bank_insights')} />
        </Card>
      )}

      <Card style={{ marginBottom: 16 }}>
        <Row style={{ justifyContent: 'space-between', marginBottom: 4 }}>
          <AppText variant="h3">RBA cash rate</AppText>
          <AppText variant="rateHero" style={{ color: theme.colors.rba }}>
            {currentRba ? formatRate(currentRba.rate) : '—'}
          </AppText>
        </Row>
        <RbaChart data={core.rba} height={190} />
        <Divider style={{ marginVertical: 12 }} />
        <AppText variant="small" weight="700" style={{ marginBottom: 8 }}>
          Recent decisions
        </AppText>
        {decisions.map((d) => {
          const up = d.rate > d.prior;
          const down = d.rate < d.prior;
          const direction = up ? 'Increased' : down ? 'Decreased' : 'Unchanged';
          return (
            <Row
              key={d.date}
              style={{ justifyContent: 'space-between', paddingVertical: 6 }}
              accessible
              accessibilityRole="text"
              accessibilityLabel={rbaDecisionA11yLabel(d.prior, d.rate, formatRunDate(d.date))}
            >
              <AppText variant="small" color="textMuted">
                {formatRunDate(d.date)}
              </AppText>
              <Row gap={6}>
                <AppText variant="tiny" color="textFaint">
                  {direction}
                </AppText>
                {up || down ? (
                  <Ionicons
                    name={up ? 'arrow-up' : 'arrow-down'}
                    size={14}
                    color={up ? theme.colors.danger : theme.colors.success}
                  />
                ) : null}
                <AppText variant="small" weight="700">
                  {formatRate(d.prior)} → {formatRate(d.rate)}
                </AppText>
              </Row>
            </Row>
          );
        })}
      </Card>

      {showBankInsights && bankInsights ? (
        <Card style={{ marginBottom: 16 }}>
          <Row style={{ justifyContent: 'space-between', marginBottom: 10 }}>
            <AppText variant="h3">RBA pass-through</AppText>
            <Chip label="PRO" selected />
          </Row>
          <RbaPassThroughCard payload={bankInsights} rba={core.rba} />
        </Card>
      ) : null}

      <Card style={{ marginBottom: 16 }}>
        <Row style={{ justifyContent: 'space-between', marginBottom: 10 }}>
          <View>
            <AppText variant="h3">History ribbon</AppText>
            <AppText variant="tiny" color="textFaint">
              Min / mean / max
            </AppText>
          </View>
          <Chip label="PRO" selected={showHistoryRibbon} />
        </Row>
        {showHistoryRibbon ? (
          <>
            {sectionOptions.length > 1 ? (
              <SegmentedControl
                options={sectionOptions}
                value={activeSection}
                onChange={setActiveSection}
              />
            ) : null}
            {historyModel ? (
              <ChartErrorBoundary name="BankHistoryChart">
                <BankHistoryChart
                  dates={historyModel.dates}
                  points={historyModel.points}
                  allDates={historyModel.allDates}
                  rba={core.rba}
                  section={activeSection}
                  height={210}
                />
              </ChartErrorBoundary>
            ) : null}
            {historyBanksError ? (
              <Row style={{ justifyContent: 'space-between', marginTop: 8 }}>
                <AppText variant="tiny" color="danger" style={{ flex: 1 }}>
                  {historyBanksError}
                </AppText>
                <Button
                  title="Retry"
                  variant="ghost"
                  onPress={handleRetryHistory}
                  loading={retryingHistory}
                  disabled={retryingHistory}
                />
              </Row>
            ) : null}
          </>
        ) : (
          <Button
            title="Enable in Settings"
            icon="sparkles"
            variant="secondary"
            onPress={() => router.push('/(tabs)/settings')}
          />
        )}
      </Card>

      <AppText variant="h3" style={{ marginBottom: 10 }}>
        Market snapshot
      </AppText>
      {interestSections.map((key) => {
        const data = core.sections[key];
        if (!data) return null;
        const stats = resolveSectionRibbonStats(data, data.rates, false);
        if (stats.min === null) return null;
        const best = bestRow(data.rates, key);
        const bestLabel = rateValueLabel(key, 'best');
        const bestRate = best ? formatRate(best.rate) : '—';
        return (
          <Pressable
            key={key}
            onPress={() => openBrowse(key)}
            accessibilityRole="button"
            accessibilityLabel={`${SECTIONS[key].title}, ${bestLabel} ${bestRate}`}
          >
            <Card style={{ marginBottom: 12 }}>
              <Row style={{ justifyContent: 'space-between', marginBottom: 12 }}>
                <Row gap={8}>
                  <Ionicons
                    name={SECTIONS[key].icon as keyof typeof Ionicons.glyphMap}
                    size={18}
                    color={SECTIONS[key].accentColor}
                  />
                  <AppText variant="body" weight="700">
                    {SECTIONS[key].title}
                  </AppText>
                </Row>
                <View style={{ alignItems: 'flex-end' }}>
                  <AppText variant="tiny" color="textFaint">
                    {bestLabel}
                  </AppText>
                  <AppText
                    variant="body"
                    weight="800"
                    style={{
                      color: SECTIONS[key].lowerIsBetter ? theme.colors.rateLoan : theme.colors.rateDeposit,
                    }}
                  >
                    {bestRate}
                  </AppText>
                </View>
              </Row>
              <Ribbon stats={stats} section={key} />
            </Card>
          </Pressable>
        );
      })}
      <AppText variant="tiny" color="textFaint" style={{ textAlign: 'center', marginTop: 8 }}>
        Snapshot from {formatRunDate(core.run_date)}
      </AppText>
      <ProPaywall visible={paywallVisible} intent={paywallIntent} onClose={closePaywall} />
    </ScreenScrollView>
  );
}
