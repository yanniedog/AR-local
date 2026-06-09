import { Ionicons } from '@expo/vector-icons';
import { Stack, useLocalSearchParams } from 'expo-router';
import React, { useEffect } from 'react';
import { Share, View } from 'react-native';

import { BankAvatar } from '../../src/components/BankAvatar';
import { EmptyState } from '../../src/components/feedback';
import { ScreenScrollView } from '../../src/components/Screen';
import { AppText, Button, Card, Divider, IconButton, Row } from '../../src/components/ui';
import { SECTIONS } from '../../src/constants';
import {
  formatBalanceRange,
  formatRate,
  formatTerm,
  humanizeEnum,
  isNonStandard,
  relativeDate,
} from '../../src/data/format';
import { sortRows } from '../../src/data/selectors';
import { findByKey } from '../../src/data/selectors';
import { useStore } from '../../src/data/store';
import { openBank } from '../../src/lib/nav';
import type { DetailItem, RateRow, SectionKey } from '../../src/types';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function ProductDetail() {
  const theme = useTheme();
  // expo-router already returns the decoded param — do NOT decode again (keys can
  // contain a literal '%', which would throw URIError). `ri` pins the tapped rate row.
  const { key, ri } = useLocalSearchParams<{ key: string; ri?: string }>();
  const productKey = key ?? '';
  const rateIndex = ri != null && ri !== '' ? Number(ri) : null;
  const core = useStore((s) => s.core);
  const ensureDetails = useStore((s) => s.ensureDetails);
  const detail = useStore((s) => s.details?.products[productKey] ?? null);
  const detailsLoading = useStore((s) => s.detailsLoading);
  const favorite = useStore((s) => s.favorites.includes(productKey));
  const toggleFavorite = useStore((s) => s.toggleFavorite);

  useEffect(() => {
    void ensureDetails();
  }, [ensureDetails]);

  const found = core ? findByKey(core.sections, productKey) : null;

  if (!found) {
    return (
      <>
        <Stack.Screen options={{ title: 'Product' }} />
        <EmptyState icon="alert-circle-outline" title="Product not found" />
      </>
    );
  }

  const { section, siblings } = found;
  // Headline = the exact row the user tapped (by rate_index), falling back to the
  // product's first row when navigated without one (e.g. from search).
  const row =
    (rateIndex != null ? siblings.find((s) => s.rate_index === rateIndex) : undefined) ?? found.row;
  const meta = SECTIONS[section];
  const accent = meta.lowerIsBetter ? theme.colors.success : theme.colors.primary;
  const rateRows = sortRows(siblings, 'rate', section);

  const onShare = () =>
    Share.share({
      message: `${row.provider} — ${row.product_name}: ${formatRate(row.rate)} (${meta.title}, AR Rates)`,
    }).catch(() => {});

  return (
    <>
      <Stack.Screen
        options={{
          title: row.provider,
          headerRight: () => (
            <Row gap={2}>
              <IconButton
                icon={favorite ? 'star' : 'star-outline'}
                color={favorite ? 'warning' : 'text'}
                onPress={() => toggleFavorite(productKey)}
                accessibilityLabel="Toggle favourite"
              />
              <IconButton icon="share-outline" onPress={onShare} accessibilityLabel="Share" />
            </Row>
          ),
        }}
      />
      <ScreenScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
        <Row gap={14} style={{ marginBottom: 16 }}>
          <BankAvatar provider={row.provider} size={56} />
          <View style={{ flex: 1 }}>
            <AppText variant="h3">{row.product_name}</AppText>
            <AppText variant="small" color="textMuted">
              {row.provider} · {meta.title}
            </AppText>
          </View>
        </Row>

        <Card style={{ marginBottom: 16, alignItems: 'center' }}>
          <AppText variant="small" color="textMuted">
            {meta.lowerIsBetter ? 'Advertised rate' : 'Interest rate'}
          </AppText>
          <AppText variant="h1" weight="800" style={{ color: accent, marginVertical: 2 }}>
            {formatRate(row.rate)}
          </AppText>
          {row.comparison_rate ? (
            <AppText variant="small" color="textFaint">
              {formatRate(row.comparison_rate)} comparison rate
            </AppText>
          ) : null}
          {isNonStandard(row) ? (
            <View
              style={{
                marginTop: 8,
                paddingHorizontal: 10,
                paddingVertical: 4,
                borderRadius: theme.radius.sm,
                backgroundColor: theme.colors.chip,
              }}
            >
              <AppText variant="tiny" weight="700" style={{ color: theme.colors.warning }}>
                Non-standard account
              </AppText>
            </View>
          ) : null}
        </Card>

        {detail?.description ? (
          <AppText variant="small" color="textMuted" style={{ marginBottom: 16, lineHeight: 20 }}>
            {detail.description}
          </AppText>
        ) : null}

        {/* All rate rows for this product */}
        <SectionTitle text={`Rates (${rateRows.length})`} />
        <Card style={{ marginBottom: 16 }}>
          {rateRows.map((r, i) => (
            <View key={`${r.rate_index}-${i}`}>
              {i > 0 ? <Divider style={{ marginVertical: 10 }} /> : null}
              <RateRowLine row={r} section={section} accent={accent} />
            </View>
          ))}
        </Card>

        <DetailGroup title="Features" icon="checkmark-circle-outline" items={detail?.features} loading={detailsLoading} />
        <DetailGroup title="Fees" icon="cash-outline" items={detail?.fees} loading={detailsLoading} />
        <DetailGroup title="Eligibility" icon="person-outline" items={detail?.eligibility} loading={detailsLoading} />
        <DetailGroup title="Constraints" icon="lock-closed-outline" items={detail?.constraints} loading={detailsLoading} />

        <Button
          title={`View all ${row.provider} products`}
          icon="business-outline"
          variant="secondary"
          style={{ marginTop: 4 }}
          onPress={() => openBank(row.provider)}
        />
        {row.last_updated ? (
          <AppText variant="tiny" color="textFaint" style={{ textAlign: 'center', marginTop: 14 }}>
            Lender data updated {relativeDate(row.last_updated)}
          </AppText>
        ) : null}
      </ScreenScrollView>
    </>
  );
}

function RateRowLine({ row, section, accent }: { row: RateRow; section: SectionKey; accent: string }) {
  const bits: string[] = [];
  if (row.rate_type) bits.push(humanizeEnum(row.rate_type));
  const term = formatTerm(row);
  if (term) bits.push(term);
  if (section === 'Mortgage') {
    if (row.ribbon_repayment_type ?? row.repayment_type)
      bits.push(humanizeEnum(row.ribbon_repayment_type ?? row.repayment_type));
    if (row.lvr_tier) bits.push(humanizeEnum(row.lvr_tier));
  } else {
    const bal = formatBalanceRange(row.balance_min, row.balance_max);
    if (bal) bits.push(bal);
  }
  return (
    <Row style={{ justifyContent: 'space-between', gap: 12 }}>
      <AppText variant="small" color="textMuted" style={{ flex: 1 }}>
        {bits.join(' · ') || 'Standard'}
      </AppText>
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

function DetailGroup({
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
          <AppText variant="small" color="textFaint">
            Loading…
          </AppText>
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

function SectionTitle({ text, icon }: { text: string; icon?: keyof typeof Ionicons.glyphMap }) {
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
