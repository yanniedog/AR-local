import { Ionicons } from '@expo/vector-icons';
import React, { useMemo } from 'react';
import { Pressable } from 'react-native';

import { RbaChart } from '../../src/components/charts';
import { Ribbon } from '../../src/components/Ribbon';
import { ScreenScrollView } from '../../src/components/Screen';
import { AppText, Card, Divider, Row } from '../../src/components/ui';
import { SECTIONS, SECTION_ORDER } from '../../src/constants';
import { formatRate, formatRunDate } from '../../src/data/format';
import { bestRow } from '../../src/data/selectors';
import { statsFor } from '../../src/data/taxonomy';
import { useStore } from '../../src/data/store';
import { openBrowse } from '../../src/lib/nav';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function Trends() {
  const theme = useTheme();
  const core = useStore((s) => s.core);

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
          <AppText variant="h2" weight="800" style={{ color: theme.colors.primary }}>
            {currentRba ? `${currentRba.rate.toFixed(2)}%` : '—'}
          </AppText>
        </Row>
        <RbaChart data={core.rba} height={190} />
        <Divider style={{ marginVertical: 12 }} />
        <AppText variant="small" weight="700" style={{ marginBottom: 8 }}>
          Recent decisions
        </AppText>
        {decisions.map((d) => {
          const up = d.rate > d.prior;
          return (
            <Row key={d.date} style={{ justifyContent: 'space-between', paddingVertical: 6 }}>
              <AppText variant="small" color="textMuted">
                {formatRunDate(d.date)}
              </AppText>
              <Row gap={6}>
                <Ionicons
                  name={up ? 'arrow-up' : 'arrow-down'}
                  size={14}
                  color={up ? theme.colors.danger : theme.colors.success}
                />
                <AppText variant="small" weight="700">
                  {d.prior.toFixed(2)}% → {d.rate.toFixed(2)}%
                </AppText>
              </Row>
            </Row>
          );
        })}
      </Card>

      <AppText variant="h3" style={{ marginBottom: 10 }}>
        Market snapshot
      </AppText>
      {SECTION_ORDER.map((key) => {
        const data = core.sections[key];
        if (!data) return null;
        const stats = statsFor(data.rates);
        if (stats.min === null) return null;
        const best = bestRow(data.rates, key);
        return (
          <Pressable key={key} onPress={() => openBrowse(key)}>
            <Card style={{ marginBottom: 12 }}>
              <Row style={{ justifyContent: 'space-between', marginBottom: 12 }}>
                <Row gap={8}>
                  <Ionicons
                    name={SECTIONS[key].icon as keyof typeof Ionicons.glyphMap}
                    size={18}
                    color={theme.colors.primary}
                  />
                  <AppText variant="body" weight="700">
                    {SECTIONS[key].title}
                  </AppText>
                </Row>
                <AppText
                  variant="body"
                  weight="800"
                  style={{ color: SECTIONS[key].lowerIsBetter ? theme.colors.success : theme.colors.primary }}
                >
                  {best ? formatRate(best.rate) : '—'}
                </AppText>
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
