import { Ionicons } from '@expo/vector-icons';
import { Stack, useLocalSearchParams } from 'expo-router';
import React, { useEffect } from 'react';
import { Alert, Linking, Pressable, Share, View } from 'react-native';

import { BankAvatar } from '../../src/components/BankAvatar';
import { BankHistoryChart } from '../../src/components/BankHistoryChart';
import { ChartErrorBoundary } from '../../src/components/ChartErrorBoundary';
import { DetailLoadingLines, EmptyState } from '../../src/components/feedback';
import { ProPaywall } from '../../src/components/ProPaywall';
import { ScreenScrollView } from '../../src/components/Screen';
import { AppText, Badge, Button, Card, Divider, IconButton, Row } from '../../src/components/ui';
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
import { selectBankHistoryChartModel } from '../../src/data/historySelectors';
import { hasProductSeries, productSeriesRecord } from '../../src/data/productHistory';
import { ensurePermissions, registerBackgroundRefresh } from '../../src/data/notifications';
import { useStore } from '../../src/data/store';
import { useProPaywall } from '../../src/hooks/useProPaywall';
import { openBank } from '../../src/lib/nav';
import { rateQualifier } from '../../src/lib/rateQualifier';
import { assessAccess } from '../../src/data/access';
import { logSwallowedError } from '../../src/lib/degradationLog';
import { canAddAlertSubscription, effectiveHistoryRibbon } from '../../src/lib/proAccess';
import type { DetailItem, ProductDetail as ProductDetailData, RateRow, SectionKey } from '../../src/types';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function ProductDetail() {
  const theme = useTheme();
  // expo-router already returns the decoded param — do NOT decode again (keys can
  // contain a literal '%', which would throw URIError). `ri` pins the tapped rate row.
  const { key, ri } = useLocalSearchParams<{ key: string; ri?: string }>();
  const productKey = key ?? '';
  const rateIndex = ri != null && ri !== '' ? Number(ri) : null;
  const core = useStore((s) => s.core);
  const coreSha = useStore((s) => s.manifest?.files.core.sha256);
  const ensureDetails = useStore((s) => s.ensureDetails);
  const detail = useStore((s) => s.details?.products[productKey] ?? null);
  const detailsLoading = useStore((s) => s.detailsLoading);
  const favorite = useStore((s) => s.favorites.includes(productKey));
  const toggleFavorite = useStore((s) => s.toggleFavorite);
  const notificationsEnabled = useStore((s) => s.prefs.notificationsEnabled);
  const setPref = useStore((s) => s.setPref);
  const subscribed = useStore((s) => s.isProductSubscribed(productKey, rateIndex));
  const subscribeProduct = useStore((s) => s.subscribeProduct);
  const unsubscribeProduct = useStore((s) => s.unsubscribeProduct);
  const subscriptions = useStore((s) => s.subscriptions);
  const includeNonStandard = useStore((s) => s.prefs.includeNonStandard);
  const historyEnabled = useStore((s) => effectiveHistoryRibbon(s.prefs));
  const historyBanks = useStore((s) => s.historyBanks);
  const productHistory = useStore((s) => s.productHistory);
  const productHistoryError = useStore((s) => s.productHistoryError);
  const ensureHistoryBanks = useStore((s) => s.ensureHistoryBanks);
  const ensureProductHistory = useStore((s) => s.ensureProductHistory);
  const { paywallVisible, paywallIntent, requestPro, closePaywall } = useProPaywall();

  useEffect(() => {
    void ensureDetails({ forProductView: true });
  }, [ensureDetails]);

  useEffect(() => {
    if (!historyEnabled) return;
    void ensureHistoryBanks();
    void ensureProductHistory();
  }, [core?.run_date, coreSha, historyEnabled, ensureHistoryBanks, ensureProductHistory, productKey]);

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
  const qualifier = rateQualifier(row, section);

  // Section context (min/max/mean/median over time) + this product's own rate line.
  const sectionInk = meta.lowerIsBetter ? theme.colors.rateLoan : theme.colors.rateDeposit;
  const historyModel = historyEnabled
    ? selectBankHistoryChartModel({ core, historyBanks, includeNonStandard }, section, 'All')
    : null;
  const productSeries = { values: productSeriesRecord(productHistory, productKey), label: row.product_name };
  const productHasSeries = hasProductSeries(productHistory, productKey);

  const onShare = () =>
    Share.share({
      message: `${row.provider} — ${row.product_name}: ${formatRate(row.rate)} (${meta.title}, Australian Rates)`,
    }).catch((err) => logSwallowedError('product.share', err));

  const onToggleNotify = async () => {
    if (subscribed) {
      unsubscribeProduct(productKey, rateIndex);
      return;
    }
    if (!canAddAlertSubscription(subscriptions, useStore.getState().prefs)) {
      requestPro('alert_limit');
      return;
    }
    const ok = await ensurePermissions();
    if (!ok) {
      Alert.alert('Notifications disabled', 'Enable notifications for Australian Rates in system settings.');
      return;
    }
    if (!notificationsEnabled) {
      setPref('notificationsEnabled', true);
      void registerBackgroundRefresh();
    }
    subscribeProduct(productKey, rateIndex, row);
  };

  return (
    <>
      <Stack.Screen
        options={{
          title: row.provider,
          headerRight: () => (
            <Row gap={2}>
              <IconButton
                icon={subscribed ? 'notifications' : 'notifications-outline'}
                color={subscribed ? 'primary' : 'text'}
                onPress={() => void onToggleNotify()}
                accessibilityLabel={subscribed ? 'Remove rate alert' : 'Notify on rate change'}
              />
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
          {qualifier.conditional ? (
            <>
              <View
                style={{
                  marginTop: 8,
                  paddingHorizontal: 10,
                  paddingVertical: 4,
                  borderRadius: theme.radius.sm,
                  borderWidth: 1,
                  borderColor: theme.colors.warning,
                }}
              >
                <AppText variant="tiny" weight="700" style={{ color: theme.colors.warning }}>
                  {qualifier.label}
                </AppText>
              </View>
              <AppText
                variant="small"
                color="textMuted"
                style={{ marginTop: 8, textAlign: 'center', lineHeight: 18 }}
              >
                {qualifier.note}
              </AppText>
            </>
          ) : null}
        </Card>

        <AccessNotice name={row.product_name} detail={detail} loading={detailsLoading} />

        {detail?.description ? (
          <AppText variant="small" color="textMuted" style={{ marginBottom: 16, lineHeight: 20 }}>
            {detail.description}
          </AppText>
        ) : null}

        <ProductSpecs row={row} section={section} />

        <SectionTitle text="Rate history" icon="trending-up-outline" />
        <Card style={{ marginBottom: 16 }}>
          {historyEnabled ? (
            historyModel ? (
              <>
                <AppText variant="tiny" color="textFaint" style={{ marginBottom: 8 }}>
                  {row.product_name} vs all {meta.title.toLowerCase()} rates
                </AppText>
                <ChartErrorBoundary name="ProductHistoryChart">
                  <BankHistoryChart
                    dates={historyModel.dates}
                    points={historyModel.points}
                    allDates={historyModel.allDates}
                    rba={core?.rba}
                    rbaHolds={core?.rba_holds}
                    section={section}
                    height={210}
                    highlightSeries={productSeries}
                  />
                </ChartErrorBoundary>
                <HistoryLegend productColor={theme.colors.text} sectionColor={sectionInk} />
                {productHistoryError && !productHasSeries ? (
                  <Row style={{ justifyContent: 'space-between', marginTop: 8 }}>
                    <AppText variant="tiny" color="danger" style={{ flex: 1 }}>
                      Couldn&apos;t load this product&apos;s history.
                    </AppText>
                    <Button
                      title="Retry"
                      variant="ghost"
                      onPress={() => void ensureProductHistory({ force: true })}
                    />
                  </Row>
                ) : !productHasSeries ? (
                  <AppText variant="tiny" color="textFaint" style={{ marginTop: 6 }}>
                    Gathering this product&apos;s daily history…
                  </AppText>
                ) : null}
              </>
            ) : (
              <AppText variant="small" color="textMuted">
                Rate history appears once more daily snapshots are collected.
              </AppText>
            )
          ) : (
            <>
              <AppText variant="small" color="textMuted" style={{ marginBottom: 10, lineHeight: 20 }}>
                See how {row.product_name}&apos;s rate moved over time against the market&apos;s mean and median.
              </AppText>
              <Button
                title="Unlock rate history"
                icon="sparkles"
                variant="secondary"
                onPress={() => {
                  if (requestPro('history_ribbon')) setPref('showHistoryRibbon', true);
                }}
              />
            </>
          )}
        </Card>

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

        <OfficialLinks links={detail?.links} />

        <Button
          title={subscribed ? 'Rate alert on' : 'Notify on rate change'}
          icon={subscribed ? 'notifications' : 'notifications-outline'}
          variant={subscribed ? 'secondary' : 'primary'}
          style={{ marginBottom: 8 }}
          onPress={() => void onToggleNotify()}
        />
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
      <ProPaywall
        visible={paywallVisible}
        intent={paywallIntent}
        onClose={closePaywall}
        onUpgraded={() => {
          if (paywallIntent === 'history_ribbon') setPref('showHistoryRibbon', true);
        }}
      />
    </>
  );
}

function RateRowLine({ row, section, accent }: { row: RateRow; section: SectionKey; accent: string }) {
  const theme = useTheme();
  const q = rateQualifier(row, section);
  const bits: string[] = [];
  // The badge already conveys generic bonus/intro, so drop only the rate_type
  // values it duplicates (BONUS / INTRODUCTORY). Keep more specific ones like
  // BUNDLE_BONUS that add information the badge doesn't (e.g. needs a linked
  // account). The intro term is likewise carried by the badge (suppressed below).
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
  // Don't fall back to "Standard" for a conditional row that has no other
  // metadata — it contradicts the badge (e.g. "Bonus · Standard"). Show the
  // badge alone in that case.
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

/** "Who can get this" — surfaces public-availability / eligibility restrictions. */
function AccessNotice({
  name,
  detail,
  loading,
}: {
  name: string;
  detail: ProductDetailData | null;
  loading: boolean;
}) {
  const theme = useTheme();
  // Wait for details so we don't briefly assert a name-only restriction.
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

/** Links to the lender's authoritative overview / eligibility / fees / terms pages. */
function OfficialLinks({ links }: { links?: ProductDetailData['links'] }) {
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

/** Tabulated specifications for the headline rate row. */
function ProductSpecs({ row, section }: { row: RateRow; section: SectionKey }) {
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

function HistoryLegend({ productColor, sectionColor }: { productColor: string; sectionColor: string }) {
  return (
    <Row gap={16} style={{ marginTop: 10, flexWrap: 'wrap' }}>
      <LegendItem color={productColor} label="This product" />
      <LegendItem color={sectionColor} label="Median" dashed />
      <LegendItem color={sectionColor} label="Mean" />
    </Row>
  );
}

function LegendItem({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
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
