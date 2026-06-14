import { Ionicons } from '@expo/vector-icons';
import React, { useState } from 'react';
import { ScrollView, View } from 'react-native';

import type { BankInsightsPayload } from '../../data/bankInsights';
import type { BankHistoryChartModel, Brand, HistoryWindow, RbaEntry, SectionKey } from '../../types';
import { SECTIONS } from '../../constants';
import { BankHistoryChart } from '../BankHistoryChart';
import { ChartErrorBoundary } from '../ChartErrorBoundary';
import { AppText, Chip, Row } from '../ui';
import { LenderRaceChart } from './LenderRaceChart';
import { MarketSeismograph } from './MarketSeismograph';
import { RateHeatCalendar } from './RateHeatCalendar';
import { RbaResponseScatter } from './RbaResponseScatter';
import { SwitcherEdgeChart } from './SwitcherEdgeChart';

export type HistoryViewMode = 'ribbon' | 'calendar' | 'race' | 'edge' | 'pulse' | 'rba';

const MODE_META: Record<HistoryViewMode, { label: string; icon: keyof typeof Ionicons.glyphMap; blurb: string }> = {
  ribbon: { label: 'Ribbon', icon: 'analytics-outline', blurb: 'Min / median / mean / max range over time' },
  calendar: { label: 'Calendar', icon: 'calendar-outline', blurb: 'Every day, coloured by which way rates moved' },
  race: { label: 'Race', icon: 'podium-outline', blurb: "Today's leaders, traced back through the rankings" },
  edge: { label: 'Edge', icon: 'flash-outline', blurb: 'What switching beats the typical rate by' },
  pulse: { label: 'Pulse', icon: 'pulse-outline', blurb: 'Daily rate-move activity across all lenders' },
  rba: { label: 'RBA map', icon: 'navigate-outline', blurb: 'Who passed the RBA decision on — how fast, how fully' },
};

const WINDOW_OPTIONS: HistoryWindow[] = ['30D', '90D', '1Y', 'All'];

/**
 * History explorer: one card, six lenses on the same history series. Ribbon /
 * calendar / edge read the section aggregates; race / pulse / RBA map read the
 * per-bank intelligence asset.
 */
export function HistoryExplorer({
  section,
  historyModel,
  insights,
  insightsAvailable,
  rba,
  brands,
  selectedDate,
  onDateSelect,
}: {
  section: SectionKey;
  historyModel: BankHistoryChartModel | null;
  insights: BankInsightsPayload | null;
  /** Pro bank-intelligence modes are renderable (asset enabled for this user). */
  insightsAvailable: boolean;
  rba: RbaEntry[];
  brands?: Record<string, Brand>;
  selectedDate?: string | null;
  onDateSelect?: (date: string) => void;
}) {
  const [mode, setMode] = useState<HistoryViewMode>('ribbon');
  const [window, setWindow] = useState<HistoryWindow>('90D');

  const modes: HistoryViewMode[] = ['ribbon', 'calendar', 'race', 'edge', 'pulse'];
  if (section === 'Mortgage') modes.push('rba');
  const activeMode = modes.includes(mode) ? mode : 'ribbon';
  const needsInsights = activeMode === 'race' || activeMode === 'pulse' || activeMode === 'rba';
  const showWindowChips = activeMode === 'race' || activeMode === 'pulse';

  return (
    <View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 8 }}>
        <Row gap={6}>
          {modes.map((m) => (
            <Chip
              key={m}
              label={MODE_META[m].label}
              icon={MODE_META[m].icon}
              selected={activeMode === m}
              onPress={() => setMode(m)}
            />
          ))}
        </Row>
      </ScrollView>
      <AppText variant="tiny" color="textFaint" style={{ marginBottom: 8 }}>
        {MODE_META[activeMode].blurb}
      </AppText>

      {showWindowChips ? (
        <Row gap={6} style={{ marginBottom: 8, flexWrap: 'wrap' }}>
          {WINDOW_OPTIONS.map((w) => (
            <Chip key={w} label={w} selected={window === w} onPress={() => setWindow(w)} />
          ))}
        </Row>
      ) : null}

      {needsInsights && !insightsAvailable ? (
        <AppText variant="small" color="textMuted">
          This lens uses the per-bank intelligence feed — included with Pro.
        </AppText>
      ) : needsInsights && !insights ? (
        <AppText variant="small" color="textMuted">
          Loading bank intelligence…
        </AppText>
      ) : (
        <>
          {activeMode === 'ribbon' && historyModel ? (
            <ChartErrorBoundary name="BankHistoryChart">
              <BankHistoryChart
                dates={historyModel.dates}
                points={historyModel.points}
                allDates={historyModel.allDates}
                rba={rba}
                section={section}
                height={210}
                onDateSelect={onDateSelect}
              />
            </ChartErrorBoundary>
          ) : null}
          {activeMode === 'calendar' && historyModel ? (
            <ChartErrorBoundary name="RateHeatCalendar">
              <RateHeatCalendar
                dates={historyModel.allDates ?? historyModel.dates}
                points={historyModel.points}
                section={section}
                selectedDate={selectedDate}
                onDateSelect={onDateSelect}
              />
            </ChartErrorBoundary>
          ) : null}
          {activeMode === 'race' ? (
            <ChartErrorBoundary name="LenderRaceChart">
              <LenderRaceChart
                payload={insights}
                section={section}
                lowerIsBetter={SECTIONS[section].lowerIsBetter}
                window={window}
                brands={brands}
              />
            </ChartErrorBoundary>
          ) : null}
          {activeMode === 'edge' && historyModel ? (
            <ChartErrorBoundary name="SwitcherEdgeChart">
              <SwitcherEdgeChart
                dates={historyModel.dates}
                points={historyModel.points}
                section={section}
              />
            </ChartErrorBoundary>
          ) : null}
          {activeMode === 'pulse' ? (
            <ChartErrorBoundary name="MarketSeismograph">
              <MarketSeismograph
                payload={insights}
                section={section}
                window={window}
                rba={section === 'Mortgage' ? rba : undefined}
                selectedDate={selectedDate}
                onDateSelect={onDateSelect}
              />
            </ChartErrorBoundary>
          ) : null}
          {activeMode === 'rba' ? (
            <ChartErrorBoundary name="RbaResponseScatter">
              <RbaResponseScatter payload={insights} rba={rba} />
            </ChartErrorBoundary>
          ) : null}
          {(activeMode === 'ribbon' || activeMode === 'calendar' || activeMode === 'edge') && !historyModel ? (
            <AppText variant="small" color="textMuted">
              History loads after the first refresh with the ribbon enabled.
            </AppText>
          ) : null}
        </>
      )}
    </View>
  );
}
