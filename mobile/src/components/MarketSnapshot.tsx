import React, { useMemo } from 'react';
import { Pressable, View } from 'react-native';

import { SECTIONS } from '../constants';
import { bankSnapshotAt, type BankInsightsPayload } from '../data/bankInsights';
import { formatRate, formatRunDate } from '../data/format';
import { moveTone } from '../lib/moveSemantics';
import { openBank } from '../lib/nav';
import type { SectionKey } from '../types';
import { useTheme } from '../theme/ThemeProvider';
import { BankAvatar } from './BankAvatar';
import { AppText, Divider, Row } from './ui';

function deltaLabel(bps: number): string {
  return `${bps > 0 ? '+' : '−'}${Math.abs(bps)} bps`;
}

/**
 * Rewind list for ribbon scrubbing: each lender's best rate as of `date`,
 * with its most recent move on/before that date.
 */
export function MarketSnapshotList({
  payload,
  section,
  date,
  maxRows = 12,
}: {
  payload: BankInsightsPayload | null;
  section: SectionKey;
  date: string;
  maxRows?: number;
}) {
  const theme = useTheme();
  const lowerIsBetter = SECTIONS[section].lowerIsBetter;
  const rows = useMemo(
    () => bankSnapshotAt(payload, section, date, lowerIsBetter).slice(0, maxRows),
    [payload, section, date, lowerIsBetter, maxRows],
  );
  if (!payload) {
    return (
      <AppText variant="small" color="textMuted">
        Bank-level rewind needs bank intelligence data — it loads with Charts &amp; trends.
      </AppText>
    );
  }
  if (!rows.length) {
    return (
      <AppText variant="small" color="textMuted">
        No {SECTIONS[section].short.toLowerCase()} data on or before {formatRunDate(date)}.
      </AppText>
    );
  }
  return (
    <View>
      {rows.map((row, i) => {
        const tone = row.changeBps ? moveTone(section, row.changeBps) : 'muted';
        return (
          <React.Fragment key={row.provider}>
            {i > 0 ? <Divider /> : null}
            <Pressable
              onPress={() => openBank(row.provider)}
              accessibilityRole="button"
              accessibilityLabel={`${row.provider}, best ${SECTIONS[section].short} rate ${
                row.best != null ? formatRate(row.best) : 'unknown'
              } on ${formatRunDate(date)}`}
            >
              <Row gap={10} style={{ paddingVertical: 6 }}>
                <BankAvatar provider={row.provider} size={28} />
                <View style={{ flex: 1 }}>
                  <AppText variant="small" weight="600" numberOfLines={1}>
                    {row.provider}
                  </AppText>
                  {row.changeBps && row.changedOn ? (
                    <AppText variant="tiny" color="textFaint" numberOfLines={1}>
                      moved {formatRunDate(row.changedOn)}
                    </AppText>
                  ) : null}
                </View>
                {row.changeBps ? (
                  <AppText
                    variant="tiny"
                    weight="800"
                    style={{
                      color: tone === 'danger' ? theme.colors.danger : theme.colors.success,
                    }}
                  >
                    {deltaLabel(row.changeBps)}
                  </AppText>
                ) : null}
                <AppText variant="small" weight="800" style={{ minWidth: 56, textAlign: 'right' }}>
                  {row.best != null ? formatRate(row.best) : '—'}
                </AppText>
              </Row>
            </Pressable>
          </React.Fragment>
        );
      })}
    </View>
  );
}
