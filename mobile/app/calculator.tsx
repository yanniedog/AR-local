import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { BankAvatar } from '../src/components/BankAvatar';
import { ProfileEditor } from '../src/components/ProfileEditor';
import { ScreenScrollView } from '../src/components/Screen';
import { SegmentedControl } from '../src/components/controls';
import { AppText, Badge, Card, Row } from '../src/components/ui';
import { SECTIONS } from '../src/constants';
import { assessAccess } from '../src/data/access';
import { computeLvr, depositToReachLvr, num, type CalcInputs } from '../src/data/calc';
import { formatRate, humanizeEnum, isBroadlyAvailable, toFraction } from '../src/data/format';
import { sectionSegmentOptions } from '../src/data/interests';
import { lvrTierForValue, parseLvrTier, profileFilterRows } from '../src/data/profile';
import { distinctValues } from '../src/data/selectors';
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

const formatDollars = (n: number): string => `$${Math.round(n).toLocaleString('en-AU')}`;

interface Candidate {
  row: RateRow;
  rate: number;
  perMonth: number; // mortgage: repayment saved per month; deposits: extra interest per month
  total: number; // mortgage: saved over remaining term; deposits: extra interest per year
}

export default function Calculator() {
  const theme = useTheme();
  const core = useStore((s) => s.core);
  const details = useStore((s) => s.details);
  const interests = useStore((s) => s.prefs.interests);
  const profileFilters = useStore((s) => s.prefs.profileFilters);
  const includeNonStandard = useStore((s) => s.prefs.includeNonStandard);
  const savedCalc = useStore((s) => s.prefs.calc);
  const setPref = useStore((s) => s.setPref);
  const activeSection = useStore((s) => s.activeSection);
  const [section, setSection] = useState<SectionKey>(activeSection);
  const sectionOptions = useMemo(() => sectionSegmentOptions(interests), [interests]);

  const isLoan = SECTIONS[section].lowerIsBetter;
  const isMortgage = section === 'Mortgage';

  // Inputs live on the user profile so the calculator remembers the situation.
  const [inputs, setInputs] = useState<CalcInputs>(savedCalc);
  const upd = (patch: Partial<CalcInputs>) => setInputs((prev) => ({ ...prev, ...patch }));
  useEffect(() => {
    const t = setTimeout(() => setPref('calc', inputs), 400);
    return () => clearTimeout(t);
  }, [inputs, setPref]);

  // Profile-matched comparable rows for the section (e.g. OO + P&I + your LVR).
  const rows = useMemo(() => {
    const all = core?.sections?.[section]?.rates ?? [];
    return profileFilterRows(rowsUnder(all, section, []), profileFilters, section).filter(
      (r) => !!r && (includeNonStandard || isBroadlyAvailable(r)),
    );
  }, [core, section, profileFilters, includeNonStandard]);

  const median = useMemo(() => statsFor(rows, true).median, [rows]);

  // ---- LVR (mortgage): a real calculation from several inputs ----
  const lvrResult = useMemo(() => computeLvr(inputs), [inputs]);
  const lvr = isMortgage ? lvrResult.lvr : null;
  const availableLvrTiers = useMemo(
    () => distinctValues(core?.sections?.Mortgage?.rates ?? [], 'lvr_tier'),
    [core],
  );
  const lvrBand = lvr !== null ? lvrTierForValue(lvr, availableLvrTiers) : null;

  // Retain the identified band on the profile so every comparison is like-for-like.
  useEffect(() => {
    if (!lvrBand) return;
    const current = profileFilters.lvrTiers;
    if (current.length === 1 && current[0] === lvrBand) return;
    setPref('profileFilters', { ...profileFilters, lvrTiers: [lvrBand] });
  }, [lvrBand, profileFilters, setPref]);

  // Deposit needed to drop into the next lower LVR band (better rates).
  const nextBandHint = useMemo(() => {
    if (!isMortgage || inputs.mode !== 'buy' || !lvrBand) return null;
    const band = parseLvrTier(lvrBand);
    const propertyValue = num(inputs.propertyValue);
    if (!band || band.lo <= 0 || propertyValue <= 0) return null;
    const extra = depositToReachLvr(propertyValue, lvrResult.depositApplied, band.lo);
    if (extra <= 0) return null;
    return { extra, targetPct: band.lo };
  }, [isMortgage, inputs.mode, inputs.propertyValue, lvrBand, lvrResult.depositApplied]);

  // Loan amount that drives the savings comparison.
  const balance = isMortgage
    ? lvrResult.loan ?? 0
    : num(inputs.savingsBalance) || 50000;

  const currentRate = (() => {
    const pct = Number((inputs.currentRate || '').trim().replace(/%$/, ''));
    if (isFinite(pct) && pct > 0) return pct / 100;
    return median ?? null;
  })();
  const years = Math.min(40, Math.max(1, num(inputs.years) || 25));
  const months = Math.round(years * 12);

  const candidates = useMemo<Candidate[]>(() => {
    if (currentRate === null || balance <= 0) return [];
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

  const field = (
    label: string,
    value: string,
    onChangeText: (t: string) => void,
    placeholder: string,
    a11y: string,
    width?: number,
  ) => (
    <View style={width ? { width } : { flex: 1 }}>
      <AppText variant="tiny" color="textFaint" style={{ marginBottom: 4 }}>
        {label}
      </AppText>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={theme.colors.textFaint}
        keyboardType="numeric"
        style={inputStyle}
        accessibilityLabel={a11y}
      />
    </View>
  );

  return (
    <ScreenScrollView contentContainerStyle={{ padding: 16, paddingBottom: 32 }} keyboardShouldPersistTaps="handled">
      {sectionOptions.length > 1 ? (
        <View style={{ marginBottom: 12 }}>
          <SegmentedControl options={sectionOptions} value={section} onChange={setSection} />
        </View>
      ) : null}

      <Card style={{ marginBottom: 16 }}>
        {isMortgage ? (
          <>
            <View style={{ marginBottom: 10 }}>
              <SegmentedControl<CalcInputs['mode']>
                options={[
                  { label: 'Buying', value: 'buy' },
                  { label: 'Refinancing', value: 'refi' },
                ]}
                value={inputs.mode}
                onChange={(mode) => upd({ mode })}
              />
            </View>
            {inputs.mode === 'buy' ? (
              <>
                <Row gap={10}>
                  {field('Property price ($)', inputs.propertyValue, (t) => upd({ propertyValue: t }), '650,000', 'Property price in dollars')}
                  {field('Your savings ($)', inputs.deposit, (t) => upd({ deposit: t }), '130,000', 'Savings available as deposit')}
                </Row>
                <Row gap={10} style={{ marginTop: 10 }}>
                  {field('Upfront costs ($)', inputs.costs, (t) => upd({ costs: t }), 'stamp duty + fees', 'Upfront costs paid from savings')}
                  <View style={{ flex: 1, justifyContent: 'flex-end' }}>
                    <AppText variant="tiny" color="textFaint" style={{ marginBottom: 4 }}>
                      Loan needed
                    </AppText>
                    <AppText variant="body" weight="800" style={{ paddingVertical: 10 }}>
                      {lvrResult.loan != null ? formatDollars(lvrResult.loan) : '—'}
                    </AppText>
                  </View>
                </Row>
              </>
            ) : (
              <Row gap={10}>
                {field('Property value ($)', inputs.propertyValue, (t) => upd({ propertyValue: t }), '800,000', 'Current property value')}
                {field('Current loan ($)', inputs.loanBalance, (t) => upd({ loanBalance: t }), '600,000', 'Current loan balance')}
              </Row>
            )}

            {lvr !== null ? (
              <View style={{ marginTop: 12 }}>
                <Row gap={8} style={{ alignItems: 'center', flexWrap: 'wrap' }}>
                  <AppText variant="small" weight="800">
                    LVR {lvr.toFixed(lvr < 100 ? 1 : 0)}%
                  </AppText>
                  {lvrBand ? (
                    <Badge label={humanizeEnum(lvrBand)} tone="success" />
                  ) : (
                    <AppText variant="tiny" color="textFaint">above tracked LVR bands</AppText>
                  )}
                </Row>
                {lvrBand ? (
                  <AppText variant="tiny" style={{ color: theme.colors.success, marginTop: 4 }}>
                    Saved to your profile — comparisons below match your LVR band.
                  </AppText>
                ) : null}
                {nextBandHint ? (
                  <AppText variant="tiny" color="textMuted" style={{ marginTop: 4 }}>
                    Add {formatDollars(nextBandHint.extra)} deposit to reach the ≤{nextBandHint.targetPct}% band and
                    unlock lower-LVR rates.
                  </AppText>
                ) : null}
              </View>
            ) : (
              <AppText variant="tiny" color="textFaint" style={{ marginTop: 10 }}>
                {inputs.mode === 'buy'
                  ? 'Enter the property price and your savings to calculate your LVR — we’ll save the band to your profile.'
                  : 'Enter the property value and current loan to calculate your LVR.'}
              </AppText>
            )}

            <Row gap={10} style={{ marginTop: 12 }}>
              {field('Current rate (%)', inputs.currentRate, (t) => upd({ currentRate: t }), median !== null ? (median * 100).toFixed(2) : '6.00', 'Current interest rate percent')}
              {field('Years left', inputs.years, (t) => upd({ years: t }), '25', 'Years remaining on loan', 86)}
            </Row>
          </>
        ) : (
          <>
            <AppText variant="small" weight="700" style={{ marginBottom: 10 }}>
              Your current balance
            </AppText>
            <Row gap={10}>
              {field('Balance ($)', inputs.savingsBalance, (t) => upd({ savingsBalance: t }), '50,000', 'Balance in dollars')}
              {field('Current rate (%)', inputs.currentRate, (t) => upd({ currentRate: t }), median !== null ? (median * 100).toFixed(2) : '4.50', 'Current interest rate percent')}
            </Row>
          </>
        )}
      </Card>

      {isMortgage ? (
        <Card style={{ marginBottom: 16 }}>
          <AppText variant="small" weight="700" style={{ marginBottom: 4 }}>
            Your mortgage profile
          </AppText>
          <AppText variant="tiny" color="textFaint" style={{ marginBottom: 12 }}>
            Tune what you’re comparing against. Your LVR band is set automatically from the figures above —
            tap a different LVR tier to override it.
          </AppText>
          <ProfileEditor
            sections={['Mortgage']}
            value={profileFilters}
            onChange={(next) => setPref('profileFilters', next)}
          />
        </Card>
      ) : null}

      <AppText variant="small" weight="700" color="textMuted" style={{ marginBottom: 8 }}>
        {candidates.length
          ? isLoan
            ? 'WHAT SWITCHING COULD SAVE'
            : 'WHAT SWITCHING COULD EARN'
          : currentRate === null
            ? 'ENTER YOUR CURRENT RATE'
            : balance <= 0
              ? 'ENTER YOUR LOAN DETAILS ABOVE'
              : 'NO BETTER COMPARABLE RATES FOUND'}
      </AppText>
      {candidates.map((c) => {
        const access = assessAccess(c.row.product_name, details?.products?.[c.row.product_key] ?? null);
        return (
          <Pressable
            key={c.row.provider}
            onPress={() => openProduct(c.row.product_key, c.row.rate_index)}
            accessibilityRole="button"
            accessibilityLabel={`View ${c.row.provider} ${c.row.product_name}, ${formatRate(c.rate)}`}
          >
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
                  {access.badge ? (
                    <AppText variant="tiny" weight="700" style={{ color: theme.colors.warning, marginTop: 2 }}>
                      {access.verify ? `${access.badge}?` : access.badge}
                    </AppText>
                  ) : null}
                </View>
                <View style={{ alignItems: 'flex-end' }}>
                  <AppText variant="body" weight="800" style={{ color: theme.colors.success }}>
                    {formatDollars(c.perMonth)}/mo
                  </AppText>
                  <AppText variant="tiny" color="textFaint">
                    {formatDollars(c.total)} {isLoan ? 'over term' : 'per year'}
                  </AppText>
                </View>
                <AppText variant="body" color="textFaint" style={{ marginLeft: 2 }}>
                  ›
                </AppText>
              </Row>
            </Card>
          </Pressable>
        );
      })}

      <AppText variant="tiny" color="textFaint" style={{ marginTop: 8, lineHeight: 16 }}>
        Estimates use advertised CDR rates and exclude fees, bonus-rate conditions and switching
        costs. {isMortgage ? 'LVR is loan ÷ property value; repayments assume principal & interest over the years remaining. Some market-leading products are restricted (staff/occupation/membership) — check each product’s eligibility.' : ''}
      </AppText>
    </ScreenScrollView>
  );
}
