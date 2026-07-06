import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Linking, Pressable, View } from 'react-native';

import { DetailLoadingLines } from '../feedback';
import { AppText, Badge, Card, Divider, Row } from '../ui';
import {
  formatBalanceRange,
  formatRate,
  formatTerm,
  humanizeEnum,
  isNonStandard,
  relativeDate,
} from '../../data/format';
import { assessAccess } from '../../data/access';
import { rateQualifier } from '../../lib/rateQualifier';
import type { DetailItem, ProductDetail as ProductDetailData, RateRow, SectionKey } from '../../types';
import { useTheme } from '../../theme/ThemeProvider';

export function RateRowLine({ row, section, accent }: { row: RateRow; section: SectionKey; accent: string }) {
  const theme = useTheme();
  const q = rateQualifier(row, section);
  const bits: string[] = [];
  const rt = row.rate_type?.toUpperCase();
  const rtRedundant = q.conditional && (rt === 'BONUS' || rt === 'INTRODUCTORY' || rt === 'INTRO');
  if (row.rate_type && !rtRedundant) bits.push(humanizeEnum(row.rate_type));
  const term = formatTerm(row);
  if (term && q.kind !== 'intro') bits.push(term);
  if (section === 'Mortgage') {
    if (row.ribbon_repayment_type ?? row.repayment_type)
      bits.push(humanizeEnum(row.ribbon_repayment_type ?? row.repayment_type));
    if (row.lvr_tier) bits.push(humanizeEnum(row.lvr_tier));
  } else {
    const bal = formatBalanceRange(row.balance_min, row.balance_max);
    if (bal) bits.push(bal);
  }
  const descriptor = bits.join(' · ') || (q.conditional ? '' : 'Standard');
  return (
    <Row style={{ justifyContent: 'space-between', gap: 12 }}>
      <Row style={{ flex: 1, alignItems: 'center', gap: 6 }}>
        {q.conditional ? (
          <View
            style={{
              flexShrink: 0,
              paddingHorizontal: 6,
              paddingVertical: 1,
              borderRadius: theme.radius.sm,
              borderWidth: 1,
              borderColor: theme.colors.warning,
            }}
          >
            <AppText variant="tiny" weight="700" numberOfLines={1} style={{ color: theme.colors.warning }}>
              {q.shortLabel}
            </AppText>
          </View>
        ) : null}
        {descriptor ? (
          <AppText variant="small" color="textMuted" style={{ flex: 1, flexShrink: 1 }}>
            {descriptor}
          </AppText>
        ) : null}
      </Row>
      <Row gap={8}>
        <AppText variant="body" weight="800" style={{ color: accent }}>
          {formatRate(row.rate)}
        </AppText>
        {row.comparison_rate ? (
          <AppText variant="tiny" color="textFaint">
            {formatRate(row.comparison_rate)} cmp
          </AppText>
        ) : null}
      </Row>
    </Row>
  );
}

export function DetailGroup({
  title,
  icon,
  items,
  loading,
}: {
  title: string;
  icon: keyof typeof Ionicons.glyphMap;
  items?: DetailItem[];
  loading: boolean;
}) {
  if ((!items || items.length === 0) && !loading) return null;
  return (
    <View style={{ marginBottom: 16 }}>
      <SectionTitle text={title} icon={icon} />
      <Card>
        {loading && !items ? (
          <DetailLoadingLines />
        ) : (
          (items ?? []).map((it, i) => (
            <View key={i}>
              {i > 0 ? <Divider style={{ marginVertical: 10 }} /> : null}
              <Row style={{ justifyContent: 'space-between', gap: 12 }}>
                <AppText variant="small" weight="600" style={{ flex: 1 }}>
                  {it.name || humanizeEnum(it.label)}
                </AppText>
                {it.value !== undefined ? (
                  <AppText variant="small" color="textMuted">
                    {String(it.value)}
                  </AppText>
                ) : null}
              </Row>
              {it.info ? (
                <AppText variant="tiny" color="textFaint" style={{ marginTop: 2, lineHeight: 16 }}>
                  {it.info}
                </AppText>
              ) : null}
            </View>
          ))
        )}
      </Card>
    </View>
  );
}

export function AccessNotice({
  name,
  detail,
  loading,
}: {
  name: string;
  detail: ProductDetailData | null;
  loading: boolean;
}) {
  const theme = useTheme();
  if (loading && !detail) return null;
  const a = assessAccess(name, detail);
  if (!a.restricted && !a.verify) return null;
  const tone = theme.colors.warning;
  return (
    <Card style={{ marginBottom: 16, borderLeftWidth: 3, borderLeftColor: tone }}>
      <Row gap={8} style={{ alignItems: 'center', marginBottom: 6, flexWrap: 'wrap' }}>
        <Ionicons name={a.verify ? 'alert-circle-outline' : 'people-outline'} size={16} color={tone} />
        <AppText variant="small" weight="700">Who can get this</AppText>
        {a.badge ? <Badge label={a.badge} tone="warning" /> : null}
      </Row>
      <AppText variant="small" color="textMuted" style={{ lineHeight: 20 }}>
        {a.summary}
      </AppText>
      {detail?.links?.eligibility ? (
        <Pressable
          onPress={() => void Linking.openURL(detail.links!.eligibility!)}
          accessibilityRole="link"
          style={{ marginTop: 8 }}
        >
          <Row gap={6} style={{ alignItems: 'center' }}>
            <Ionicons name="open-outline" size={14} color={theme.colors.primary} />
            <AppText variant="small" weight="700" style={{ color: theme.colors.primary }}>
              Check the lender’s eligibility criteria
            </AppText>
          </Row>
        </Pressable>
      ) : null}
    </Card>
  );
}

export function OfficialLinks({ links }: { links?: ProductDetailData['links'] }) {
  const theme = useTheme();
  if (!links) return null;
  const all: { label: string; url?: string; icon: keyof typeof Ionicons.glyphMap }[] = [
    { label: 'Product overview', url: links.overview, icon: 'document-text-outline' },
    { label: 'Eligibility criteria', url: links.eligibility, icon: 'person-outline' },
    { label: 'Fees & pricing', url: links.fees, icon: 'cash-outline' },
    { label: 'Terms & conditions', url: links.terms, icon: 'reader-outline' },
  ];
  const items = all.filter((i) => !!i.url);
  if (!items.length) return null;
  return (
    <View style={{ marginBottom: 16 }}>
      <SectionTitle text="Official details" icon="link-outline" />
      <Card>
        {items.map((it, i) => (
          <View key={it.label}>
            {i > 0 ? <Divider style={{ marginVertical: 4 }} /> : null}
            <Pressable
              onPress={() => void Linking.openURL(it.url!)}
              accessibilityRole="link"
              accessibilityLabel={`${it.label} (opens lender website)`}
              style={{ paddingVertical: 8 }}
            >
              <Row gap={10} style={{ alignItems: 'center' }}>
                <Ionicons name={it.icon} size={16} color={theme.colors.primary} />
                <AppText variant="small" weight="600" style={{ flex: 1, color: theme.colors.primary }}>
                  {it.label}
                </AppText>
                <Ionicons name="open-outline" size={15} color={theme.colors.textFaint} />
              </Row>
            </Pressable>
          </View>
        ))}
      </Card>
      <AppText variant="tiny" color="textFaint" style={{ marginTop: 6, marginLeft: 4 }}>
        Authoritative, up-to-date detail straight from the lender (CDR).
      </AppText>
    </View>
  );
}

export function SectionTitle({ text, icon }: { text: string; icon?: keyof typeof Ionicons.glyphMap }) {
  const theme = useTheme();
  return (
    <Row gap={6} style={{ marginBottom: 8, marginLeft: 4 }}>
      {icon ? <Ionicons name={icon} size={15} color={theme.colors.textMuted} /> : null}
      <AppText variant="small" weight="700" color="textMuted">
        {text.toUpperCase()}
      </AppText>
    </Row>
  );
}

export function ProductSpecs({ row, section }: { row: RateRow; section: SectionKey }) {
  const specs: { label: string; value: string }[] = [];
  const add = (label: string, value?: string | null) => {
    const v = value == null ? '' : String(value).trim();
    if (v) specs.push({ label, value: v });
  };

  add('Rate type', humanizeEnum(row.rate_type));
  if (section === 'Mortgage') {
    add('Structure', humanizeEnum(row.ribbon_rate_structure));
    add('Repayment', humanizeEnum(row.ribbon_repayment_type ?? row.repayment_type));
    add('Loan purpose', humanizeEnum(row.loan_purpose ?? row.security_purpose));
    add('LVR tier', humanizeEnum(row.lvr_tier));
  } else {
    add('Deposit type', humanizeEnum(row.ribbon_deposit_kind));
    add('Balance range', formatBalanceRange(row.balance_min, row.balance_max));
    add('Interest paid', humanizeEnum(row.interest_payment));
  }
  add('Term', formatTerm(row));
  add('Comparison rate', row.comparison_rate ? formatRate(row.comparison_rate) : null);
  add('Account type', humanizeEnum(row.account_type));
  add('Features', humanizeEnum(row.feature_set));
  add('Category', humanizeEnum(row.category));
  add('Account class', isNonStandard(row) ? 'Non-standard' : 'Standard');
  add('Product ID', row.product_id);
  add('Data updated', row.last_updated ? relativeDate(row.last_updated) : null);

  if (!specs.length) return null;
  return (
    <View style={{ marginBottom: 16 }}>
      <SectionTitle text="Specifications" icon="list-outline" />
      <Card>
        {specs.map((s, i) => (
          <View key={s.label}>
            {i > 0 ? <Divider style={{ marginVertical: 10 }} /> : null}
            <Row style={{ justifyContent: 'space-between', gap: 12 }}>
              <AppText variant="small" color="textMuted">
                {s.label}
              </AppText>
              <AppText variant="small" weight="600" style={{ flex: 1, textAlign: 'right' }}>
                {s.value}
              </AppText>
            </Row>
          </View>
        ))}
      </Card>
    </View>
  );
}

export function HistoryLegend({ productColor, sectionColor }: { productColor: string; sectionColor: string }) {
  return (
    <Row gap={16} style={{ marginTop: 10, flexWrap: 'wrap' }}>
      <LegendItem color={productColor} label="This product" />
      <LegendItem color={sectionColor} label="Median" dashed />
      <LegendItem color={sectionColor} label="Mean" />
    </Row>
  );
}

export function LegendItem({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <Row gap={6}>
      <View
        style={{
          width: 16,
          height: 0,
          borderTopWidth: 2.4,
          borderColor: color,
          borderStyle: dashed ? 'dashed' : 'solid',
        }}
      />
      <AppText variant="tiny" color="textMuted">
        {label}
      </AppText>
    </Row>
  );
}
