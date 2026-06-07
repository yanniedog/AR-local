import { useLocalSearchParams } from 'expo-router';
import React, { useMemo } from 'react';
import { ScrollView, View } from 'react-native';

import { BankAvatar } from '../src/components/BankAvatar';
import { EmptyState } from '../src/components/feedback';
import { AppText, Card, Divider } from '../src/components/ui';
import { SECTIONS } from '../src/constants';
import {
  formatBalanceRange,
  formatRate,
  formatTerm,
  humanizeEnum,
  toFraction,
} from '../src/data/format';
import { findByKey } from '../src/data/selectors';
import { useStore } from '../src/data/store';
import type { RateRow, SectionKey } from '../src/types';
import { useTheme } from '../src/theme/ThemeProvider';

interface Entry {
  row: RateRow;
  section: SectionKey;
}

export default function Compare() {
  const theme = useTheme();
  const { keys } = useLocalSearchParams<{ keys: string }>();
  const core = useStore((s) => s.core);

  const entries = useMemo<Entry[]>(() => {
    if (!core || !keys) return [];
    let list: string[];
    try {
      // Keys are serialized as a JSON array (product keys can contain commas).
      list = JSON.parse(keys);
    } catch {
      list = keys.split(',');
    }
    return list
      .map((token) => {
        // Browse selections are "<rate_index>#<product_key>" to pin the exact row;
        // watchlist passes bare product_keys. rate_index is numeric, so split on the
        // first '#' only when it's preceded solely by digits.
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
    return <EmptyState icon="git-compare-outline" title="Nothing to compare" subtitle="Select at least two products." />;
  }

  // Only mark a single "BEST" when every product shares a section (so the better
  // direction is well-defined). Mixed-category watchlist compares skip the badge.
  const sameSection = entries.every((e) => e.section === entries[0].section);
  const lowerIsBetter = SECTIONS[entries[0].section].lowerIsBetter;
  const fractions = entries.map((e) => toFraction(e.row.rate));
  const valid = fractions.filter((f): f is number => f !== null);
  const bestVal =
    sameSection && valid.length ? (lowerIsBetter ? Math.min(...valid) : Math.max(...valid)) : null;

  const rows: { label: string; get: (e: Entry) => string }[] = [
    { label: 'Comparison rate', get: (e) => (e.row.comparison_rate ? formatRate(e.row.comparison_rate) : '—') },
    { label: 'Type', get: (e) => humanizeEnum(e.row.rate_type) || '—' },
    { label: 'Term', get: (e) => formatTerm(e.row) || '—' },
    {
      label: 'Repayment',
      get: (e) => humanizeEnum(e.row.ribbon_repayment_type ?? e.row.repayment_type) || '—',
    },
    { label: 'LVR', get: (e) => humanizeEnum(e.row.lvr_tier) || '—' },
    { label: 'Balance', get: (e) => formatBalanceRange(e.row.balance_min, e.row.balance_max) || '—' },
    { label: 'Account', get: (e) => (e.row.account_class === 'non_standard' ? 'Non-standard' : 'Standard') },
  ];

  return (
    <ScrollView horizontal contentContainerStyle={{ padding: 16 }} showsHorizontalScrollIndicator>
      {entries.map((e, idx) => {
        const f = fractions[idx];
        const isBest = bestVal !== null && f === bestVal;
        const accent = SECTIONS[e.section].lowerIsBetter ? theme.colors.success : theme.colors.primary;
        return (
          <Card
            key={e.row.product_key}
            style={{
              width: 230,
              marginRight: 12,
              borderColor: isBest ? accent : theme.colors.border,
              borderWidth: isBest ? 2 : 1,
            }}
          >
            <BankAvatar provider={e.row.provider} size={40} />
            <AppText variant="body" weight="700" numberOfLines={2} style={{ marginTop: 8, minHeight: 40 }}>
              {e.row.product_name}
            </AppText>
            <AppText variant="tiny" color="textMuted" numberOfLines={1}>
              {e.row.provider}
            </AppText>

            <View style={{ alignItems: 'center', marginVertical: 12 }}>
              {isBest ? (
                <AppText variant="tiny" weight="800" style={{ color: accent, marginBottom: 2 }}>
                  ★ BEST
                </AppText>
              ) : null}
              <AppText variant="h1" weight="800" style={{ color: accent }}>
                {formatRate(e.row.rate)}
              </AppText>
            </View>

            {rows.map((r, i) => (
              <View key={r.label}>
                {i === 0 ? <Divider style={{ marginBottom: 8 }} /> : null}
                <View style={{ paddingVertical: 5 }}>
                  <AppText variant="tiny" color="textFaint">
                    {r.label}
                  </AppText>
                  <AppText variant="small" weight="600" numberOfLines={2}>
                    {r.get(e)}
                  </AppText>
                </View>
                <Divider />
              </View>
            ))}
          </Card>
        );
      })}
    </ScrollView>
  );
}
