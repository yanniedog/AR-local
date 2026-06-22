import React from 'react';
import { View } from 'react-native';

import { RbaCountdownCard } from '../src/components/RbaCountdownCard';
import { ScreenScrollView } from '../src/components/Screen';
import { AppText, Card, Divider, Row } from '../src/components/ui';
import { decisionLine, formatRbaDate, rbaTrend, recentDecisions } from '../src/data/rbaCalendar';
import { useStore } from '../src/data/store';
import { useTheme } from '../src/theme/ThemeProvider';

/** "Why rates move" — a calm macro read of the RBA's recent rate path: the current
 * cash rate, a rules-based trend summary, the next-decision countdown, and the full
 * recent decision history. Reached from the Home shortcut. */
export default function WhyRatesMove() {
  const theme = useTheme();
  const calendar = useStore((s) => s.rbaCalendar);
  const trend = rbaTrend(calendar);
  const decisions = recentDecisions(calendar, 12);

  return (
    <ScreenScrollView>
      <Card>
        <AppText variant="tiny" weight="700" color="textFaint">
          CASH RATE
        </AppText>
        <AppText variant="rateHero" style={{ color: theme.colors.rba, marginTop: theme.spacing(1) }}>
          {trend.rate != null ? `${trend.rate.toFixed(2)}%` : '—'}
        </AppText>
        <AppText variant="small" color="textMuted" style={{ marginTop: theme.spacing(2) }}>
          {trend.summary || 'Recent RBA decisions will appear once the latest data syncs.'}
        </AppText>
        <AppText variant="tiny" color="textFaint" style={{ marginTop: theme.spacing(2) }}>
          A read of the RBA's recent decisions — not a forecast.
        </AppText>
      </Card>

      <RbaCountdownCard />

      {decisions.length ? (
        <Card>
          <AppText variant="tiny" weight="700" color="textFaint" style={{ marginBottom: theme.spacing(2) }}>
            RECENT DECISIONS
          </AppText>
          {decisions.map((decision, index) => (
            <View key={decision.date}>
              {index > 0 ? <Divider style={{ marginVertical: theme.spacing(2) }} /> : null}
              <Row style={{ justifyContent: 'space-between' }}>
                <AppText variant="small" color="textMuted">
                  {formatRbaDate(decision.date)}
                </AppText>
                <AppText variant="small" weight="600">
                  {decisionLine(decision)}
                </AppText>
              </Row>
            </View>
          ))}
        </Card>
      ) : null}
    </ScreenScrollView>
  );
}
