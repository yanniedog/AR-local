import { Ionicons } from '@expo/vector-icons';
import * as Application from 'expo-application';
import { useScrollToTop } from '@react-navigation/native';
import { useLocalSearchParams, useRouter, type Href } from 'expo-router';
import React, { useCallback, useEffect, useRef } from 'react';
import { Alert, ScrollView, View } from 'react-native';

import { SegmentedControl } from '../../src/components/controls';
import { ProPaywall } from '../../src/components/ProPaywall';
import { Screen, ScreenScrollView } from '../../src/components/Screen';
import { UndoSnackbar } from '../../src/components/Snackbar';
import { SubscriptionRow } from '../../src/components/SubscriptionRow';
import { TouchTarget } from '../../src/components/TouchTarget';
import { AppText, Button, Chip, Divider, Row } from '../../src/components/ui';
import { AccountSecurityRows } from '../../src/components/settings/AccountSecurityRows';
import { AppUpdateSection } from '../../src/components/settings/AppUpdateSection';
import {
  InfoRow,
  InterestOrderRow,
  Label,
  Section,
  ToggleRow,
} from '../../src/components/settings/settingsUi';
import { SECTIONS, SECTION_ORDER } from '../../src/constants';
import { formatRunDate, relativeDate } from '../../src/data/format';
import { moveInterest, orderedInterestSections, toggleInterest } from '../../src/data/interests';
import {
  ensurePermissions,
  registerBackgroundRefresh,
  unregisterBackgroundRefresh,
} from '../../src/data/notifications';
import { useStore } from '../../src/data/store';
import type { RankMetric } from '../../src/data/selectors';
import { useProPaywall } from '../../src/hooks/useProPaywall';
import { setDiagnosticsEnabled } from '../../src/lib/observability';
import type { Subscription } from '../../src/data/subscriptions';
import type { ThemeMode } from '../../src/theme/theme';
import { dataSourceLabel } from '../../src/lib/nextIngest';
import {
  effectiveDeepSearch,
  effectiveHistoryRibbon,
  hasProAccess,
  RATE_INTELLIGENCE_PRO,
} from '../../src/lib/proAccess';
import { useTheme } from '../../src/theme/ThemeProvider';
import { useUndoSnackbar } from '../../src/hooks/useUndoSnackbar';

const THRESHOLDS = [1, 5, 10, 25];

export default function Settings() {
  const router = useRouter();
  const prefs = useStore((s) => s.prefs);
  const setPref = useStore((s) => s.setPref);
  const core = useStore((s) => s.core);
  const source = useStore((s) => s.source);
  const refresh = useStore((s) => s.refresh);
  const clearCache = useStore((s) => s.clearCache);
  const lastCheckedAt = useStore((s) => s.lastCheckedAt);
  const subscriptions = useStore((s) => s.subscriptions);
  const removeSubscription = useStore((s) => s.removeSubscription);
  const restoreSubscription = useStore((s) => s.restoreSubscription);
  const { snack, showUndo, undo } = useUndoSnackbar();
  const theme = useTheme();
  const { paywallVisible, paywallIntent, requestPro, closePaywall } = useProPaywall();
  const scrollRef = useRef<ScrollView>(null);
  useScrollToTop(scrollRef);

  const { focus, t } = useLocalSearchParams<{ focus?: string; t?: string }>();
  const updateSectionY = useRef(0);
  useEffect(() => {
    if (focus !== 'update') return;
    const id = setTimeout(() => {
      scrollRef.current?.scrollTo({ y: Math.max(0, updateSectionY.current - 8), animated: true });
      router.setParams({ focus: undefined, t: undefined });
    }, 350);
    return () => clearTimeout(id);
  }, [focus, t, router]);

  const onToggleDeepSearch = (value: boolean) => {
    if (!value) {
      setPref('enableDeepSearch', false);
      return;
    }
    if (!requestPro('deep_search')) return;
    setPref('enableDeepSearch', true);
  };

  const onToggleHistoryRibbon = (value: boolean) => {
    if (!value) {
      setPref('showHistoryRibbon', false);
      return;
    }
    if (!requestPro('history_ribbon')) return;
    setPref('showHistoryRibbon', true);
  };

  const removeSubscriptionWithUndo = useCallback(
    (sub: Subscription) => {
      removeSubscription(sub.id);
      showUndo(`Removed ${sub.label}`, () => restoreSubscription(sub));
    },
    [removeSubscription, restoreSubscription, showUndo],
  );

  const onToggleNotifications = async (value: boolean) => {
    if (value) {
      const ok = await ensurePermissions();
      if (!ok) {
        Alert.alert('Notifications disabled', 'Enable notifications for Australian Rates in system settings.');
        return;
      }
      void registerBackgroundRefresh();
      setPref('notificationsEnabled', true);
    } else {
      void unregisterBackgroundRefresh();
      setPref('notificationsEnabled', false);
    }
  };

  return (
    <Screen>
    <ScreenScrollView ref={scrollRef} contentContainerStyle={{ padding: 16, paddingBottom: snack ? 96 : 40 }}>
      <Section title={RATE_INTELLIGENCE_PRO}>
        <InfoRow label="Status" value={hasProAccess(prefs) ? 'Active' : 'Free'} />
        {!hasProAccess(prefs) ? (
          <>
            <AppText variant="tiny" color="textFaint" style={{ marginTop: 6, lineHeight: 16 }}>
              1 rate alert included. Pro unlocks unlimited alerts, deep search, bank intelligence
              (rate-move feed, RBA pass-through, per-bank history), and the history explorer.
            </AppText>
            <Button
              title="Upgrade to Pro"
              icon="sparkles"
              style={{ marginTop: 10 }}
              onPress={() => {
                requestPro('bank_insights');
              }}
            />
          </>
        ) : (
          <AppText variant="tiny" color="textFaint" style={{ marginTop: 6, lineHeight: 16 }}>
            All Pro features unlocked on this device.
          </AppText>
        )}
      </Section>

      <View onLayout={(e) => { updateSectionY.current = e.nativeEvent.layout.y; }}>
        <AppUpdateSection />
      </View>

      <Section title="Personalise">
        <Button
          title="Your product profile"
          icon="person-circle-outline"
          variant="secondary"
          onPress={() => router.push('/profile' as Href)}
        />
        <AppText variant="tiny" color="textFaint" style={{ marginTop: 6, marginBottom: 12, lineHeight: 16 }}>
          Default filters (purpose, rate type, LVR…) applied across the app.
        </AppText>
        <Label text="Theme" />
        <SegmentedControl<ThemeMode>
          options={[
            { value: 'system', label: 'System' },
            { value: 'light', label: 'Light' },
            { value: 'dark', label: 'Dark' },
          ]}
          value={prefs.themeMode}
          onChange={(v) => setPref('themeMode', v)}
        />
        <Divider style={{ marginVertical: 12 }} />
        <Label text="Sections shown on Home, Browse, and Trends" />
        {orderedInterestSections(prefs.interests).map((key, idx, ordered) => (
          <InterestOrderRow
            key={key}
            title={SECTIONS[key].title}
            canMoveUp={idx > 0}
            canMoveDown={idx < ordered.length - 1}
            canRemove={ordered.length > 1}
            onMoveUp={() => setPref('interests', moveInterest(prefs.interests, key, 'up'))}
            onMoveDown={() => setPref('interests', moveInterest(prefs.interests, key, 'down'))}
            onRemove={() => setPref('interests', toggleInterest(prefs.interests, key))}
          />
        ))}
        {SECTION_ORDER.filter((key) => !prefs.interests.includes(key)).length ? (
          <>
            <Divider style={{ marginVertical: 12 }} />
            <Label text="Add section" />
            <Row gap={8} style={{ flexWrap: 'wrap' }}>
              {SECTION_ORDER.filter((key) => !prefs.interests.includes(key)).map((key) => (
                <Chip
                  key={key}
                  label={SECTIONS[key].title}
                  icon={SECTIONS[key].icon as keyof typeof Ionicons.glyphMap}
                  onPress={() => setPref('interests', toggleInterest(prefs.interests, key))}
                />
              ))}
            </Row>
          </>
        ) : null}
        <Divider style={{ marginVertical: 12 }} />
        <Label text="Default category" />
        <Row gap={8} style={{ flexWrap: 'wrap' }}>
          {orderedInterestSections(prefs.interests).map((key) => (
            <Chip
              key={key}
              label={SECTIONS[key].title}
              selected={prefs.defaultSection === key}
              onPress={() => setPref('defaultSection', key)}
            />
          ))}
        </Row>
      </Section>

      <Section title="Product filtering">
        <ToggleRow
          icon="people-outline"
          label="Show broadly applicable products by default"
          sub="Prioritise standard, broadly available rates. Hides staff-only, business, industry, foreign-investor and other narrowly available products. Turn off to include everything."
          value={!prefs.includeNonStandard}
          onChange={(v) => setPref('includeNonStandard', !v)}
        />
      </Section>

      <Section title="Rate ranking">
        <Label text="Rank savings & term deposits by" />
        <SegmentedControl<RankMetric>
          options={[
            { value: 'base', label: 'Base ongoing rate' },
            { value: 'max', label: 'Maximum rate' },
          ]}
          value={prefs.depositRankMetric}
          onChange={(v) => setPref('depositRankMetric', v)}
        />
        <AppText variant="tiny" color="textFaint" style={{ marginTop: 6, lineHeight: 16 }}>
          Base ranks by the ongoing rate you keep after any intro or bonus period — the honest
          default. Maximum ranks by the best advertised rate, including conditional bonus and
          introductory rates.
        </AppText>
      </Section>

      <Section title="Features">
        <ToggleRow
          icon="search-outline"
          label="Deep product search"
          sub={
            hasProAccess(prefs)
              ? 'Search fees and features; downloads details + search index'
              : 'Pro · search fees and features'
          }
          value={effectiveDeepSearch(prefs)}
          onChange={onToggleDeepSearch}
        />
        <Divider style={{ marginVertical: 12 }} />
        <ToggleRow
          icon="analytics-outline"
          label="History explorer"
          sub={
            hasProAccess(prefs)
              ? 'Ribbon, calendar, race, edge, pulse & RBA lenses in Trends'
              : 'Pro'
          }
          value={effectiveHistoryRibbon(prefs)}
          onChange={onToggleHistoryRibbon}
        />
        {effectiveHistoryRibbon(prefs) ? (
          <Button
            title="Open history explorer"
            icon="stats-chart"
            variant="secondary"
            style={{ marginTop: 10 }}
            onPress={() => router.push('/(tabs)/trends' as Href)}
          />
        ) : null}
      </Section>

      <Section title="Alerts">
        <ToggleRow
          icon="notifications-outline"
          label="Rate-change alerts"
          sub="Best-rate, RBA, watchlist, and your subscriptions"
          value={prefs.notificationsEnabled}
          onChange={onToggleNotifications}
        />
        {prefs.notificationsEnabled ? (
          <>
            <Divider style={{ marginVertical: 12 }} />
            <Label text="Alert threshold" />
            <Row gap={8} style={{ flexWrap: 'wrap' }}>
              {THRESHOLDS.map((bps) => (
                <Chip
                  key={bps}
                  label={`${bps} bps`}
                  selected={prefs.rateMoveThresholdBps === bps}
                  onPress={() => setPref('rateMoveThresholdBps', bps)}
                />
              ))}
            </Row>
            <Divider style={{ marginVertical: 12 }} />
            <Label text={`Subscriptions (${subscriptions.length})`} />
            {subscriptions.length ? (
              subscriptions.map((sub: Subscription) => (
                <SubscriptionRow
                  key={sub.id}
                  kind={sub.kind === 'product' ? 'Product' : 'Search'}
                  label={sub.label}
                  onSwipeRemove={() => removeSubscriptionWithUndo(sub)}
                  onConfirmRemove={() => removeSubscription(sub.id)}
                />
              ))
            ) : (
              <AppText variant="tiny" color="textFaint">
                None — add from a product or search screen.
              </AppText>
            )}
          </>
        ) : null}
      </Section>

      <Section title="Data & storage">
        <ToggleRow
          icon="wifi-outline"
          label="Refresh on Wi-Fi only"
          sub="Skip background updates on cellular"
          value={prefs.wifiOnly}
          onChange={(v) => setPref('wifiOnly', v)}
        />
        <Divider style={{ marginVertical: 12 }} />
        <InfoRow label="Data set" value={core ? formatRunDate(core.run_date) : '—'} />
        <InfoRow label="Source" value={dataSourceLabel(source)} />
        <InfoRow label="Last checked" value={lastCheckedAt ? relativeDate(lastCheckedAt) : 'never'} />
        <InfoRow label="Lenders" value={core ? String(Object.keys(core.brands ?? {}).length) : '—'} />
        <Row gap={12} style={{ marginTop: 12 }}>
          <Button
            title="Refresh now"
            icon="refresh"
            variant="secondary"
            style={{ flex: 1 }}
            onPress={() => void refresh({ manual: true, force: true })}
          />
          <Button
            title="Clear cache"
            icon="trash-outline"
            variant="ghost"
            style={{ flex: 1 }}
            onPress={() =>
              Alert.alert('Clear cached data?', 'The app will re-download on next refresh.', [
                { text: 'Cancel', style: 'cancel' },
                { text: 'Clear', style: 'destructive', onPress: () => void clearCache() },
              ])
            }
          />
        </Row>
      </Section>

      <Section title="Privacy & security">
        <AccountSecurityRows
          appLockEnabled={prefs.appLockEnabled}
          onAppLockChange={(v) => setPref('appLockEnabled', v)}
        />
        <Divider style={{ marginVertical: 12 }} />
        <ToggleRow
          icon="pulse-outline"
          label="Diagnostics & crash reporting"
          sub="Clarity session replay + Firebase Crashlytics logs"
          value={prefs.diagnosticsEnabled}
          onChange={(value) => {
            setPref('diagnosticsEnabled', value);
            void setDiagnosticsEnabled(value);
          }}
        />
        <AppText variant="tiny" color="textFaint" style={{ marginTop: 8, lineHeight: 16 }}>
          Clarity records on-screen interactions for replay. Crashlytics receives crash reports
          and warn/error log lines from app flows. Disabling stops new uploads; a native rebuild
          may be required for full SDK teardown.
        </AppText>
        <Divider style={{ marginVertical: 12 }} />
        <TouchTarget
          fill
          onPress={() => router.push('/debug-log' as Href)}
          style={({ pressed }) => ({
            flexDirection: 'row',
            alignItems: 'center',
            gap: 12,
            opacity: pressed ? 0.7 : 1,
          })}
        >
          <Ionicons name="document-text-outline" size={20} color={theme.colors.primary} />
          <View style={{ flex: 1 }}>
            <AppText variant="body" weight="600">
              Debug log
            </AppText>
            <AppText variant="tiny" color="textFaint">
              View, share, or upload logs; on-disk path shown on screen
            </AppText>
          </View>
          <Ionicons name="chevron-forward" size={18} color={theme.colors.textMuted} />
        </TouchTarget>
      </Section>

      <Section title="About">
        <InfoRow
          label="Version"
          value={`${Application.nativeApplicationVersion ?? '1.0.0'} (${Application.nativeBuildVersion ?? '0'})`}
        />
        <TouchTarget
          fill
          onPress={() => router.push('/terms' as Href)}
          style={{
            marginTop: 12,
            flexDirection: 'row',
            alignItems: 'center',
            gap: 10,
          }}
        >
          <Ionicons name="document-text-outline" size={20} color={theme.colors.primary} />
          <View style={{ flex: 1 }}>
            <AppText variant="body" weight="600">Terms</AppText>
            <AppText variant="tiny" color="textFaint">Data sources and legal notices</AppText>
          </View>
          <Ionicons name="chevron-forward" size={18} color={theme.colors.textMuted} />
        </TouchTarget>
        <AppText variant="tiny" color="textFaint" style={{ marginTop: 8, lineHeight: 16 }}>
          General information only — not financial advice. Confirm rates with the lender before applying.
        </AppText>
      </Section>

      <ProPaywall
        visible={paywallVisible}
        intent={paywallIntent}
        onClose={closePaywall}
        onUpgraded={() => {
          if (paywallIntent === 'deep_search') setPref('enableDeepSearch', true);
          if (paywallIntent === 'history_ribbon') setPref('showHistoryRibbon', true);
        }}
      />
    </ScreenScrollView>
    <UndoSnackbar snack={snack} onUndo={undo} />
    </Screen>
  );
}
