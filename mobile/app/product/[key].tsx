import { Stack, useLocalSearchParams } from 'expo-router';
import React, { useEffect } from 'react';
import { Alert, Share, View } from 'react-native';

import { BankAvatar } from '../../src/components/BankAvatar';
import { BankHistoryChart } from '../../src/components/BankHistoryChart';
import { ChartErrorBoundary } from '../../src/components/ChartErrorBoundary';
import { EmptyState } from '../../src/components/feedback';
import { ProPaywall } from '../../src/components/ProPaywall';
import {
  AccessNotice,
  DetailGroup,
  HistoryLegend,
  OfficialLinks,
  ProductSpecs,
  RateRowLine,
  SectionTitle,
} from '../../src/components/product/ProductDetailParts';
import { ScreenScrollView } from '../../src/components/Screen';
import { AppText, Button, Card, Divider, IconButton, Row } from '../../src/components/ui';
import { SECTIONS } from '../../src/constants';
import { formatRate, isNonStandard } from '../../src/data/format';
import { sortRows, findByKey } from '../../src/data/selectors';
import { selectBankHistoryChartModel } from '../../src/data/historySelectors';
import { hasProductSeries, productSeriesRecord } from '../../src/data/productHistory';
import { ensurePermissions, registerBackgroundRefresh } from '../../src/data/notifications';
import { useStore } from '../../src/data/store';
import { useProPaywall } from '../../src/hooks/useProPaywall';
import { openBank } from '../../src/lib/nav';
import { rateQualifier } from '../../src/lib/rateQualifier';
import { logSwallowedError } from '../../src/lib/degradationLog';
import { canAddAlertSubscription, effectiveHistoryRibbon } from '../../src/lib/proAccess';
import { relativeDate } from '../../src/data/format';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function ProductDetail() {
  const theme = useTheme();
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
  const depositRankMetric = useStore((s) => s.prefs.depositRankMetric);
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
  const row =
    (rateIndex != null ? siblings.find((s) => s.rate_index === rateIndex) : undefined) ?? found.row;
  const meta = SECTIONS[section];
  const accent = meta.lowerIsBetter ? theme.colors.success : theme.colors.primary;
  const rateRows = sortRows(siblings, 'rate', section, depositRankMetric);
  const qualifier = rateQualifier(row, section);

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
