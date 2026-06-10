import { useLocalSearchParams } from 'expo-router';
import React, { useMemo } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { BankAvatar } from '../src/components/BankAvatar';
import { EmptyState } from '../src/components/feedback';
import { Screen } from '../src/components/Screen';
import { AppText, Badge, Divider } from '../src/components/ui';
import { SECTIONS } from '../src/constants';
import {
  formatBalanceRange,
  formatRate,
  formatTerm,
  humanizeEnum,
  isNonStandard,
  toFraction,
} from '../src/data/format';
import { findByKey } from '../src/data/selectors';
import { useStore } from '../src/data/store';
import type { RateRow, SectionKey } from '../src/types';
import { useTheme } from '../src/theme/ThemeProvider';

const LABEL_W = 108;
const COL_W = 136;
const HEADER_H = 88;
const ROW_H = 44;
const RATE_ROW_H = 52;

interface Entry {
  row: RateRow;
  section: SectionKey;
}

interface AttrRow {
  label: string;
  get: (e: Entry) => string;
  /** When true, values use tabular numerals (rates). */
  tabular?: boolean;
}

export default function Compare() {
  const theme = useTheme();
  const { keys } = useLocalSearchParams<{ keys: string }>();
  const core = useStore((s) => s.core);

  const entries = useMemo<Entry[]>(() => {
    if (!core || !keys) return [];
    let list: string[];
    try {
      list = JSON.parse(keys);
    } catch {
      list = keys.split(',');
    }
    return list
      .map((token) => {
        const m = /^(\d+)#([\s\S]+)$/.exec(token);
        const rateIndex = m ? Number(m[1]) : null;
        const key = m ? m[2] : token;
        const found = findByKey(core.sections, key);
        if (!found) return null;
        const exact =
          rateIndex !== null ? found.siblings.find((s) => s.rate_index === rateIndex) : undefined;
        return { row: exact ?? found.row, section: found.section };
      })
      .filter((x): x is Entry => x !== null);
  }, [core, keys]);

  if (!core) return null;
  if (entries.length < 2) {
    return (
      <EmptyState
        icon="git-compare-outline"
        title="Nothing to compare"
        subtitle="Select at least two products."
        fill
      />
    );
  }

  const sameSection = entries.every((e) => e.section === entries[0].section);
  const lowerIsBetter = SECTIONS[entries[0].section].lowerIsBetter;
  const fractions = entries.map((e) => toFraction(e.row.rate));
  const valid = fractions.filter((f): f is number => f !== null);
  const bestVal =
    sameSection && valid.length ? (lowerIsBetter ? Math.min(...valid) : Math.max(...valid)) : null;
  const bestTone = lowerIsBetter ? 'success' : 'primary';
  const rateColor = lowerIsBetter ? theme.colors.success : theme.colors.primary;

  const attrRows: AttrRow[] = [
    {
      label: 'Comparison rate',
      get: (e) => (e.row.comparison_rate ? formatRate(e.row.comparison_rate) : '—'),
      tabular: true,
    },
    { label: 'Type', get: (e) => humanizeEnum(e.row.rate_type) || '—' },
    { label: 'Term', get: (e) => formatTerm(e.row) || '—' },
    {
      label: 'Repayment',
      get: (e) => humanizeEnum(e.row.ribbon_repayment_type ?? e.row.repayment_type) || '—',
    },
    { label: 'LVR', get: (e) => humanizeEnum(e.row.lvr_tier) || '—' },
    { label: 'Balance', get: (e) => formatBalanceRange(e.row.balance_min, e.row.balance_max) || '—' },
    { label: 'Account', get: (e) => (isNonStandard(e.row) ? 'Non-standard' : 'Standard') },
  ];

  const labelCell = (label: string, height: number, weight: '600' | '700' = '600') => (
    <View
      key={label}
      style={[
        styles.labelCell,
        {
          width: LABEL_W,
          height,
          borderColor: theme.colors.border,
          backgroundColor: theme.colors.bg,
        },
      ]}
    >
      <AppText variant="tiny" color="textFaint" weight={weight} numberOfLines={2}>
        {label}
      </AppText>
    </View>
  );

  const valueCell = (
    key: string,
    height: number,
    content: React.ReactNode,
    highlight?: boolean,
  ) => (
    <View
      key={key}
      style={[
        styles.valueCell,
        {
          width: COL_W,
          height,
          borderColor: theme.colors.border,
          backgroundColor: highlight ? theme.colors.primaryMuted : theme.colors.card,
        },
      ]}
    >
      {content}
    </View>
  );

  return (
    <Screen style={{ padding: 16 }}>
      <View style={[styles.table, { borderColor: theme.colors.border }]}>
        <View style={styles.bodyRow}>
          {/* Frozen label column */}
          <View>
            <View
              style={[
                styles.labelCell,
                {
                  width: LABEL_W,
                  height: HEADER_H,
                  borderColor: theme.colors.border,
                  backgroundColor: theme.colors.bg,
                },
              ]}
            />
            {labelCell('Rate', RATE_ROW_H, '700')}
            {attrRows.map((r) => labelCell(r.label, ROW_H))}
          </View>

          {/* Horizontally scrollable product columns */}
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator
            style={styles.scrollArea}
            contentContainerStyle={{ flexGrow: 1 }}
          >
            <View style={{ flexDirection: 'row' }}>
              {entries.map((e, idx) => {
                const f = fractions[idx];
                const isBest = bestVal !== null && f === bestVal;
                return (
                  <View
                    key={`${e.row.product_key}#${e.row.rate_index ?? idx}`}
                    style={{ width: COL_W }}
                  >
                    {/* Product header */}
                    <View
                      style={[
                        styles.headerCell,
                        {
                          height: HEADER_H,
                          borderColor: theme.colors.border,
                          backgroundColor: theme.colors.card,
                        },
                      ]}
                    >
                      <BankAvatar provider={e.row.provider} size={28} />
                      <AppText variant="tiny" weight="700" numberOfLines={2} style={{ marginTop: 4 }}>
                        {e.row.product_name}
                      </AppText>
                      <AppText variant="tiny" color="textMuted" numberOfLines={1}>
                        {e.row.provider}
                      </AppText>
                    </View>

                    {/* Rate row */}
                    {valueCell(
                      'rate',
                      RATE_ROW_H,
                      <View style={styles.rateCell}>
                        {isBest ? <Badge label="Best" tone={bestTone} /> : null}
                        <AppText
                          variant="h3"
                          weight="800"
                          style={{ color: rateColor, fontVariant: ['tabular-nums'] }}
                        >
                          {formatRate(e.row.rate)}
                        </AppText>
                      </View>,
                      isBest,
                    )}

                    {/* Attribute rows */}
                    {attrRows.map((r) =>
                      valueCell(
                        r.label,
                        ROW_H,
                        <AppText
                          variant="small"
                          weight="600"
                          numberOfLines={2}
                          style={r.tabular ? { fontVariant: ['tabular-nums'] } : undefined}
                        >
                          {r.get(e)}
                        </AppText>,
                      ),
                    )}
                  </View>
                );
              })}
            </View>
          </ScrollView>
        </View>
      </View>

      <Divider style={{ marginTop: 16 }} />
      <AppText variant="tiny" color="textFaint" style={{ marginTop: 8 }}>
        {sameSection
          ? `${entries.length} products · scroll for more columns`
          : `${entries.length} products · mixed categories — no best badge`}
      </AppText>
    </Screen>
  );
}

const styles = StyleSheet.create({
  table: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 12,
    overflow: 'hidden',
  },
  bodyRow: {
    flexDirection: 'row',
  },
  scrollArea: {
    flex: 1,
  },
  labelCell: {
    justifyContent: 'center',
    paddingHorizontal: 10,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  headerCell: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 8,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  valueCell: {
    justifyContent: 'center',
    paddingHorizontal: 10,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  rateCell: {
    alignItems: 'flex-start',
    gap: 4,
  },
});
