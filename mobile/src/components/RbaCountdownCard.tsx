import { Ionicons } from '@expo/vector-icons';
import React, { useState } from 'react';
import { Pressable, View } from 'react-native';

import { AppText, Card, Divider, Row } from './ui';
import { decisionLine, formatRbaDate, rbaCountdown, recentDecisions } from '../data/rbaCalendar';
import { useStore } from '../data/store';
import { useTheme } from '../theme/ThemeProvider';

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
          {formatRbaDate(countdown.meeting.date)} · {when}
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
                {formatRbaDate(decision.date)}
              </AppText>
              <AppText variant="small" weight="600">
                {decisionLine(decision)}
              </AppText>
            </Row>
          ))}
        </View>
      ) : null}
    </Card>
  );
}
