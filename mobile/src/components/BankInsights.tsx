import { Ionicons } from '@expo/vector-icons';
import React, { useMemo } from 'react';
import { Pressable, View } from 'react-native';

import { SECTIONS } from '../constants';
import {
  marketPulse,
  rbaPassThrough,
  recentBankEvents,
  topMovers,
  type BankInsightsPayload,
  type BankRateEvent,
} from '../data/bankInsights';
import { formatRate, formatRunDate } from '../data/format';
import { openBank } from '../lib/nav';
import type { RbaEntry, SectionKey } from '../types';
import { useTheme } from '../theme/ThemeProvider';
import { BankAvatar } from './BankAvatar';
import { AppText, Badge, Button, Divider, Row } from './ui';

function bpsLabel(bps: number): string {
  const rounded = Math.round(bps * 10) / 10;
  return `${rounded > 0 ? '+' : rounded < 0 ? '−' : ''}${Math.abs(rounded)} bps`;
}

/** Up = pressure on borrowers (danger), down = relief (success); matches RBA list. */
function MoveArrow({ bps, size = 14 }: { bps: number; size?: number }) {
  const theme = useTheme();
  if (bps === 0) return null;
  const up = bps > 0;
  return (
    <Ionicons
      name={up ? 'arrow-up' : 'arrow-down'}
      size={size}
      color={up ? theme.colors.danger : theme.colors.success}
    />
  );
}

function eventA11yLabel(event: BankRateEvent): string {
  const verb = event.dir === 'cut' ? 'cut' : event.dir === 'hike' ? 'raised' : 'repriced';
  return `${event.provider} ${verb} ${SECTIONS[event.section].title} rates by ${bpsLabel(
    event.avg_bps,
  )} across ${event.moved} of ${event.total} products on ${formatRunDate(event.date)}`;
}

export function BankMoveRow({ event, showDate = true }: { event: BankRateEvent; showDate?: boolean }) {
  const theme = useTheme();
  const verb = event.dir === 'cut' ? 'cut' : event.dir === 'hike' ? 'hiked' : 'repriced';
  return (
    <Pressable
      onPress={() => openBank(event.provider)}
      accessibilityRole="button"
      accessibilityLabel={eventA11yLabel(event)}
    >
      <Row gap={10} style={{ paddingVertical: 8 }}>
        <BankAvatar provider={event.provider} size={34} />
        <View style={{ flex: 1 }}>
          <AppText variant="small" weight="700" numberOfLines={1}>
            {event.provider}
          </AppText>
          <AppText variant="tiny" color="textFaint" numberOfLines={1}>
            {verb} {SECTIONS[event.section].short.toLowerCase()} · {event.moved} of {event.total} products
            {showDate ? ` · ${formatRunDate(event.date)}` : ''}
          </AppText>
        </View>
        <Row gap={4}>
          <MoveArrow bps={event.avg_bps} />
          <AppText
            variant="small"
            weight="800"
            style={{ color: event.avg_bps > 0 ? theme.colors.danger : event.avg_bps < 0 ? theme.colors.success : theme.colors.textMuted }}
          >
            {bpsLabel(event.avg_bps)}
          </AppText>
        </Row>
      </Row>
    </Pressable>
  );
}

/** Headline pulse strip: "4 banks moved rates this week · 6 cuts · 1 hike". */
export function MarketPulseStrip({ payload }: { payload: BankInsightsPayload | null }) {
  const pulse = useMemo(() => marketPulse(payload, 7), [payload]);
  if (!pulse) return null;
  const quiet = pulse.banksMoved === 0;
  return (
    <Row gap={6} style={{ flexWrap: 'wrap' }}>
      <Badge
        label={
          quiet
            ? 'No bank rate moves this week'
            : `${pulse.banksMoved} bank${pulse.banksMoved === 1 ? '' : 's'} moved this week`
        }
        tone={quiet ? 'muted' : 'primary'}
      />
      {pulse.cuts ? <Badge label={`${pulse.cuts} cut${pulse.cuts === 1 ? '' : 's'}`} tone="success" /> : null}
      {pulse.hikes ? <Badge label={`${pulse.hikes} hike${pulse.hikes === 1 ? '' : 's'}`} tone="danger" /> : null}
    </Row>
  );
}

export function BankMovesFeed({
  payload,
  sections,
  limit = 8,
}: {
  payload: BankInsightsPayload | null;
  sections?: SectionKey[];
  limit?: number;
}) {
  const events = useMemo(
    () => recentBankEvents(payload, { sections, limit }),
    [payload, sections, limit],
  );
  if (!payload) {
    return (
      <AppText variant="small" color="textMuted">
        Loading bank intelligence…
      </AppText>
    );
  }
  if (!events.length) {
    return (
      <AppText variant="small" color="textMuted">
        No rate moves detected yet — the feed fills as banks reprice day by day.
      </AppText>
    );
  }
  return (
    <View>
      {events.map((event, i) => (
        <React.Fragment key={`${event.date}-${event.provider}-${event.section}`}>
          {i > 0 ? <Divider /> : null}
          <BankMoveRow event={event} />
        </React.Fragment>
      ))}
    </View>
  );
}

export function MoversLeaderboard({
  payload,
  section,
  windowDays = 30,
  perSide = 3,
}: {
  payload: BankInsightsPayload | null;
  section: SectionKey;
  windowDays?: number;
  perSide?: number;
}) {
  const theme = useTheme();
  const movers = useMemo(() => topMovers(payload, section, windowDays), [payload, section, windowDays]);
  const moved = movers.filter((m) => m.netBps !== 0);
  if (!moved.length) {
    return (
      <AppText variant="small" color="textMuted">
        No {SECTIONS[section].short.toLowerCase()} median moves in the last {windowDays} days.
      </AppText>
    );
  }
  const cutters = moved.filter((m) => m.netBps < 0).slice(0, perSide);
  const hikers = moved
    .filter((m) => m.netBps > 0)
    .slice(-perSide)
    .reverse();
  const renderRow = (provider: string, netBps: number, current: number) => (
    <Pressable
      key={provider}
      onPress={() => openBank(provider)}
      accessibilityRole="button"
      accessibilityLabel={`${provider}, net ${bpsLabel(netBps)} over ${windowDays} days, now ${formatRate(current)}`}
    >
      <Row gap={10} style={{ paddingVertical: 6 }}>
        <BankAvatar provider={provider} size={28} />
        <AppText variant="small" weight="600" numberOfLines={1} style={{ flex: 1 }}>
          {provider}
        </AppText>
        <AppText variant="tiny" color="textFaint">
          now {formatRate(current)}
        </AppText>
        <AppText
          variant="small"
          weight="800"
          style={{ color: netBps > 0 ? theme.colors.danger : theme.colors.success, minWidth: 64, textAlign: 'right' }}
        >
          {bpsLabel(netBps)}
        </AppText>
      </Row>
    </Pressable>
  );
  return (
    <View>
      {cutters.length ? (
        <>
          <AppText variant="tiny" weight="700" color="textFaint" style={{ marginBottom: 2 }}>
            BIGGEST CUTS · {windowDays}D
          </AppText>
          {cutters.map((m) => renderRow(m.provider, m.netBps, m.current))}
        </>
      ) : null}
      {hikers.length ? (
        <>
          <AppText
            variant="tiny"
            weight="700"
            color="textFaint"
            style={{ marginBottom: 2, marginTop: cutters.length ? 8 : 0 }}
          >
            BIGGEST HIKES · {windowDays}D
          </AppText>
          {hikers.map((m) => renderRow(m.provider, m.netBps, m.current))}
        </>
      ) : null}
    </View>
  );
}

export function RbaPassThroughCard({
  payload,
  rba,
  maxRows = 5,
}: {
  payload: BankInsightsPayload | null;
  rba: RbaEntry[];
  maxRows?: number;
}) {
  const theme = useTheme();
  const model = useMemo(() => rbaPassThrough(payload, rba), [payload, rba]);
  if (!model) {
    return (
      <AppText variant="small" color="textMuted">
        No RBA decision has landed inside the tracked window yet. The next cash-rate move will be
        scored here, lender by lender, as it happens.
      </AppText>
    );
  }
  const { decision, rows } = model;
  const dirWord = decision.bps < 0 ? 'cut' : 'raised';
  return (
    <View>
      <AppText variant="small" color="textMuted" style={{ marginBottom: 6 }}>
        RBA {dirWord} the cash rate by {Math.abs(decision.bps)} bps on {formatRunDate(decision.date)}.
        Best variable rates since:
      </AppText>
      {rows.slice(0, maxRows).map((row) => {
        const fullPass = decision.bps !== 0 && Math.abs(row.passedBps) >= Math.abs(decision.bps);
        return (
          <Pressable
            key={row.provider}
            onPress={() => openBank(row.provider)}
            accessibilityRole="button"
            accessibilityLabel={`${row.provider} moved ${bpsLabel(row.passedBps)} since the RBA decision${
              row.daysToFirstMove != null ? `, first move after ${row.daysToFirstMove} days` : ''
            }`}
          >
            <Row gap={10} style={{ paddingVertical: 6 }}>
              <BankAvatar provider={row.provider} size={28} />
              <View style={{ flex: 1 }}>
                <AppText variant="small" weight="600" numberOfLines={1}>
                  {row.provider}
                </AppText>
                <AppText variant="tiny" color="textFaint">
                  {row.daysToFirstMove != null
                    ? `moved after ${row.daysToFirstMove} day${row.daysToFirstMove === 1 ? '' : 's'}`
                    : 'no move detected yet'}
                </AppText>
              </View>
              {fullPass ? <Badge label="full pass" tone="success" /> : null}
              <AppText
                variant="small"
                weight="800"
                style={{
                  color:
                    row.passedBps === 0
                      ? theme.colors.textMuted
                      : row.passedBps > 0
                        ? theme.colors.danger
                        : theme.colors.success,
                  minWidth: 64,
                  textAlign: 'right',
                }}
              >
                {bpsLabel(row.passedBps)}
              </AppText>
            </Row>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Free-tier teaser: sells the historical moat without downloading anything. */
export function InsightsLockedCard({ onUnlock }: { onUnlock: () => void }) {
  const theme = useTheme();
  return (
    <View style={{ gap: 10 }}>
      <Row gap={8}>
        <Ionicons name="pulse" size={18} color={theme.colors.primary} />
        <AppText variant="body" weight="700" style={{ flex: 1 }}>
          Bank intelligence
        </AppText>
        <Badge label="PRO" tone="primary" />
      </Row>
      <AppText variant="small" color="textMuted">
        Everyone shows today's rates. Only Australian Rates tracks every bank, every day — see who
        cut, who hiked, who drags their feet after RBA decisions, and how each lender's rates moved
        over time.
      </AppText>
      <Button title="Unlock bank intelligence" icon="sparkles" onPress={onUnlock} />
    </View>
  );
}
