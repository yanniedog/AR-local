import { Ionicons } from '@expo/vector-icons';
import React, { useMemo } from 'react';
import { Pressable, View } from 'react-native';

import { RbaChart } from '../../src/components/charts';
import { Ribbon } from '../../src/components/Ribbon';
import { ScreenScrollView } from '../../src/components/Screen';
import { AppText, Card, Divider, Row } from '../../src/components/ui';
import { SECTIONS } from '../../src/constants';
import { orderedInterestSections } from '../../src/data/interests';
import { formatRate, formatRunDate } from '../../src/data/format';
import { resolveSectionRibbonStats } from '../../src/data/ribbonStats';
import { bestRow } from '../../src/data/selectors';
import { useStore } from '../../src/data/store';
import { rateValueLabel, rbaDecisionA11yLabel } from '../../src/lib/a11ySummaries';
import { openBrowse } from '../../src/lib/nav';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function Trends() {
  const theme = useTheme();
  const core = useStore((s) => s.core);
  const interests = useStore((s) => s.prefs.interests);
  const interestSections = useMemo(() => orderedInterestSections(interests), [interests]);

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
    <ScreenScrollView contentContainerStyle={{ padding: 16, paddingBottom: 32 }}>
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
    </ScreenScrollView>
  );
}
