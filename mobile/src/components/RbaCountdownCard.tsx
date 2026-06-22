import React from 'react';

import { AppText, Card, Row } from './ui';
import { rbaCountdown } from '../data/rbaCalendar';
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

/** Calm Home card counting down to the next RBA cash-rate decision. Renders nothing
 * until the rba-calendar asset has synced (an offline cold-start has no schedule). */
export function RbaCountdownCard() {
  const theme = useTheme();
  const calendar = useStore((s) => s.rbaCalendar);
  const countdown = rbaCountdown(calendar);
  if (!countdown) return null;
  const when =
    countdown.days <= 0 ? 'today' : countdown.days === 1 ? 'tomorrow' : `in ${countdown.days} days`;
  return (
    <Card>
      <Row style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <AppText variant="tiny" weight="700" color="textFaint">
          NEXT RBA DECISION
        </AppText>
        <AppText variant="small" color="textMuted" style={{ marginLeft: theme.spacing(3) }}>
          {formatMeetingDate(countdown.meeting.date)} · {when}
        </AppText>
      </Row>
    </Card>
  );
}
