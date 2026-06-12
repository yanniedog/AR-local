import React, { useMemo, useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { BankAvatar } from '../src/components/BankAvatar';
import { ScreenScrollView } from '../src/components/Screen';
import { SegmentedControl } from '../src/components/controls';
import { AppText, Card, Row } from '../src/components/ui';
import { SECTIONS } from '../src/constants';
import { formatRate, toFraction } from '../src/data/format';
import { sectionSegmentOptions } from '../src/data/interests';
import { profileFilterRows, profileSectionCount } from '../src/data/profile';
import { useStore } from '../src/data/store';
import { rowsUnder, statsFor } from '../src/data/taxonomy';
import { openProduct } from '../src/lib/nav';
import type { RateRow, SectionKey } from '../src/types';
import { useTheme } from '../src/theme/ThemeProvider';

function monthlyPayment(balance: number, annualRate: number, months: number): number {
  const r = annualRate / 12;
  if (r <= 0) return balance / months;
  return (r * balance) / (1 - Math.pow(1 + r, -months));
}

const formatDollars = (n: number): string =>
  `$${Math.round(n).toLocaleString('en-AU')}`;

interface Candidate {
  row: RateRow;
  rate: number;
  perMonth: number; // mortgage: repayment saved per month; deposits: extra interest per month
  total: number; // mortgage: saved over remaining term; deposits: extra interest per year
}

export default function Calculator() {
  const theme = useTheme();
  const core = useStore((s) => s.core);
  const interests = useStore((s) => s.prefs.interests);
  const profileFilters = useStore((s) => s.prefs.profileFilters);
  const includeNonStandard = useStore((s) => s.prefs.includeNonStandard);
  const activeSection = useStore((s) => s.activeSection);
  const [section, setSection] = useState<SectionKey>(activeSection);
  const sectionOptions = useMemo(() => sectionSegmentOptions(interests), [interests]);

  const isLoan = SECTIONS[section].lowerIsBetter;
  const [balanceText, setBalanceText] = useState('');
  const [rateText, setRateText] = useState('');
  const [yearsText, setYearsText] = useState('');

  // Profile-matched comparable rows for the section (e.g. OO + P&I + your LVR).
  const rows = useMemo(() => {
    const all = core?.sections[section]?.rates ?? [];
    return profileFilterRows(rowsUnder(all, section, []), profileFilters, section).filter(
      (r) => includeNonStandard || r.account_class !== 'non_standard',
    );
  }, [core, section, profileFilters, includeNonStandard]);

  const median = useMemo(() => statsFor(rows, true).median, [rows]);

  const balance = Number(balanceText.replace(/[^0-9.]/g, '')) || (isLoan ? 500000 : 50000);
  const currentRate = (() => {
    const v = toFraction(rateText.trim());
    return v ?? median ?? null;
  })();
  const years = Math.min(40, Math.max(1, Number(yearsText) || 25));
  const months = Math.round(years * 12);

  const candidates = useMemo<Candidate[]>(() => {
    if (currentRate === null) return [];
    // Best comparable rate per lender, then ranked by dollar benefit vs current.
    const bestByProvider = new Map<string, { row: RateRow; rate: number }>();
    for (const row of rows) {
      const v = toFraction(row.rate);
      if (v === null) continue;
      const prev = bestByProvider.get(row.provider);
      if (!prev || (isLoan ? v < prev.rate : v > prev.rate)) {
        bestByProvider.set(row.provider, { row, rate: v });
      }
    }
    const out: Candidate[] = [];
    for (const { row, rate } of bestByProvider.values()) {
      if (isLoan ? rate >= currentRate : rate <= currentRate) continue;
      if (isLoan) {
        const perMonth = monthlyPayment(balance, currentRate, months) - monthlyPayment(balance, rate, months);
        out.push({ row, rate, perMonth, total: perMonth * months });
      } else {
        const perYear = balance * (rate - currentRate);
        out.push({ row, rate, perMonth: perYear / 12, total: perYear });
      }
    }
    return out.sort((a, b) => b.perMonth - a.perMonth).slice(0, 10);
  }, [rows, currentRate, balance, months, isLoan]);

  if (!core) return null;

  const profileCount = profileSectionCount(profileFilters, section);
  const inputStyle = {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.surfaceAlt,
    color: theme.colors.text,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 16,
  } as const;

  return (
    <ScreenScrollView contentContainerStyle={{ padding: 16, paddingBottom: 32 }} keyboardShouldPersistTaps="handled">
      {sectionOptions.length > 1 ? (
        <View style={{ marginBottom: 12 }}>
          <SegmentedControl options={sectionOptions} value={section} onChange={setSection} />
        </View>
      ) : null}

      <Card style={{ marginBottom: 16 }}>
        <AppText variant="small" weight="700" style={{ marginBottom: 10 }}>
          {isLoan ? 'Your current loan' : 'Your current balance'}
        </AppText>
        <Row gap={10}>
          <View style={{ flex: 1 }}>
            <AppText variant="tiny" color="textFaint" style={{ marginBottom: 4 }}>
              Balance ($)
            </AppText>
            <TextInput
              value={balanceText}
              onChangeText={setBalanceText}
              placeholder={isLoan ? '500,000' : '50,000'}
              placeholderTextColor={theme.colors.textFaint}
              keyboardType="numeric"
              style={inputStyle}
              accessibilityLabel="Balance in dollars"
            />
          </View>
          <View style={{ flex: 1 }}>
            <AppText variant="tiny" color="textFaint" style={{ marginBottom: 4 }}>
              Current rate (%)
            </AppText>
            <TextInput
              value={rateText}
              onChangeText={setRateText}
              placeholder={median !== null ? (median * 100).toFixed(2) : '6.00'}
              placeholderTextColor={theme.colors.textFaint}
              keyboardType="numeric"
              style={inputStyle}
              accessibilityLabel="Current interest rate percent"
            />
          </View>
          {isLoan ? (
            <View style={{ width: 86 }}>
              <AppText variant="tiny" color="textFaint" style={{ marginBottom: 4 }}>
                Years left
              </AppText>
              <TextInput
                value={yearsText}
                onChangeText={setYearsText}
                placeholder="25"
                placeholderTextColor={theme.colors.textFaint}
                keyboardType="numeric"
                style={inputStyle}
                accessibilityLabel="Years remaining on loan"
              />
            </View>
          ) : null}
        </Row>
        <AppText variant="tiny" color="textFaint" style={{ marginTop: 10 }}>
          {profileCount > 0
            ? `Compared against lenders' best rates matching your profile (${profileCount} filters).`
            : 'Compared against every lender’s best advertised rate. Set your profile to compare like-for-like.'}
        </AppText>
      </Card>

      <AppText variant="small" weight="700" color="textMuted" style={{ marginBottom: 8 }}>
        {candidates.length
          ? isLoan
            ? 'WHAT SWITCHING COULD SAVE'
            : 'WHAT SWITCHING COULD EARN'
          : currentRate === null
            ? 'ENTER YOUR CURRENT RATE'
            : 'NO BETTER COMPARABLE RATES FOUND'}
      </AppText>
      {candidates.map((c) => (
        <Pressable key={c.row.provider} onPress={() => openProduct(c.row.product_key, c.row.rate_index)}>
          <Card style={{ marginBottom: 10 }}>
            <Row gap={12} style={{ alignItems: 'center' }}>
              <BankAvatar provider={c.row.provider} size={36} />
              <View style={{ flex: 1 }}>
                <AppText variant="body" weight="700" numberOfLines={1}>
                  {c.row.provider}
                </AppText>
                <AppText variant="tiny" color="textMuted" numberOfLines={1}>
                  {c.row.product_name} · {formatRate(c.rate)}
                </AppText>
              </View>
              <View style={{ alignItems: 'flex-end' }}>
                <AppText variant="body" weight="800" style={{ color: theme.colors.success }}>
                  {formatDollars(c.perMonth)}/mo
                </AppText>
                <AppText variant="tiny" color="textFaint">
                  {formatDollars(c.total)} {isLoan ? 'over term' : 'per year'}
                </AppText>
              </View>
            </Row>
          </Card>
        </Pressable>
      ))}

      <AppText variant="tiny" color="textFaint" style={{ marginTop: 8, lineHeight: 16 }}>
        Estimates use advertised CDR rates and exclude fees, bonus-rate conditions and switching
        costs. {isLoan ? 'Repayments assume principal & interest over the years remaining.' : ''}
      </AppText>
    </ScreenScrollView>
  );
}
