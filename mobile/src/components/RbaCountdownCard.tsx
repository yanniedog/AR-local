import { Ionicons } from '@expo/vector-icons';
import React, { useState } from 'react';
import { Pressable, View } from 'react-native';

import { AppText, Card, Divider, Row } from './ui';
import { rbaCountdown, recentDecisions, type RbaDecisionEntry } from '../data/rbaCalendar';
import { useStore } from '../data/store';
import { useTheme } from '../theme/ThemeProvider';

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

function formatMeetingDate(ymd: string): string {
  const [y, m, d] = ymd.split('-').map((part) => Number.parseInt(part, 10));
  if (!y || !m || !d || m < 1 || m > 12) return ymd;
  return `${d} ${MONTHS[m - 1]}`;
}

function decisionDetail(decision: RbaDecisionEntry): string {
  if (decision.outcome === 'hold') return `Held · ${decision.rate.toFixed(2)}%`;
  const sign = decision.outcome === 'hike' ? '+' : '−';
  return `${sign}${Math.abs(decision.delta_bps)} bps · ${decision.rate.toFixed(2)}%`;
}

/** Calm Home card counting down to the next RBA cash-rate decision; tap to reveal
 * the most recent decisions (tiered disclosure). Renders nothing until the
 * rba-calendar asset has synced (an offline cold-start has no schedule). */
export function RbaCountdownCard() {
  const theme = useTheme();
  const calendar = useStore((s) => s.rbaCalendar);
  const [expanded, setExpanded] = useState(false);
  const countdown = rbaCountdown(calendar);
  if (!countdown) return null;
  const days = countdown.calendarDays;
  const when = days <= 0 ? 'today' : days === 1 ? 'tomorrow' : `in ${days} days`;
  const recent = recentDecisions(calendar, 4);
  const hasRecent = recent.length > 0;

  const header = (
    <Row style={{ justifyContent: 'space-between' }}>
      <AppText variant="tiny" weight="700" color="textFaint">
        NEXT RBA DECISION
      </AppText>
      <Row gap={theme.spacing(2)}>
        <AppText variant="small" color="textMuted">
          {formatMeetingDate(countdown.meeting.date)} · {when}
        </AppText>
        {hasRecent ? (
          <Ionicons
            name={expanded ? 'chevron-up' : 'chevron-down'}
            size={16}
            color={theme.colors.textFaint}
          />
        ) : null}
      </Row>
    </Row>
  );

  return (
    <Card>
      {hasRecent ? (
        <Pressable
          onPress={() => setExpanded((value) => !value)}
          accessibilityRole="button"
          accessibilityState={{ expanded }}
          accessibilityHint={expanded ? 'Hide recent RBA decisions' : 'Show recent RBA decisions'}
        >
          {header}
        </Pressable>
      ) : (
        header
      )}
      {expanded && hasRecent ? (
        <View style={{ marginTop: theme.spacing(3) }}>
          <Divider />
          {recent.map((decision) => (
            <Row
              key={decision.date}
              style={{ justifyContent: 'space-between', marginTop: theme.spacing(2) }}
            >
              <AppText variant="small" color="textMuted">
                {formatMeetingDate(decision.date)}
              </AppText>
              <AppText variant="small" weight="600">
                {decisionDetail(decision)}
              </AppText>
            </Row>
          ))}
        </View>
      ) : null}
    </Card>
  );
}
