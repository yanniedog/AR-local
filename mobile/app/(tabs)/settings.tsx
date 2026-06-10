import { Ionicons } from '@expo/vector-icons';
import * as Application from 'expo-application';
import { useRouter, type Href } from 'expo-router';
import React, { useCallback, useEffect, useState } from 'react';
import { Alert, AppState, Linking, Platform, Pressable, ScrollView, Switch, View } from 'react-native';

import { SegmentedControl } from '../../src/components/controls';
import { ProPaywall } from '../../src/components/ProPaywall';
import { Screen, ScreenScrollView } from '../../src/components/Screen';
import { UndoSnackbar } from '../../src/components/Snackbar';
import { SubscriptionRow } from '../../src/components/SubscriptionRow';
import { TOUCH_TARGET_MIN, TouchTarget } from '../../src/components/TouchTarget';
import { AppText, Button, Card, Chip, Divider, IconButton, Row } from '../../src/components/ui';
import { SECTIONS, SECTION_ORDER } from '../../src/constants';
import { formatRunDate, relativeDate } from '../../src/data/format';
import { moveInterest, orderedInterestSections, toggleInterest } from '../../src/data/interests';
import {
  ensurePermissions,
  registerBackgroundRefresh,
  unregisterBackgroundRefresh,
} from '../../src/data/notifications';
import { useStore } from '../../src/data/store';
import { useProPaywall } from '../../src/hooks/useProPaywall';
import {
  checkForAppUpdate,
  downloadAndInstallUpdate,
  getInstalledAppInfo,
  type ApkManifest,
  type UpdateCheckResult,
  type VersionChangelogSummary,
} from '../../src/lib/appUpdate';
import {
  canInstallApkUpdates,
  ensureInstallPermission,
  openInstallPermissionSettings,
} from '../../src/lib/installPermission';
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
    <ScreenScrollView contentContainerStyle={{ padding: 16, paddingBottom: snack ? 96 : 40 }}>
      <Section title={RATE_INTELLIGENCE_PRO}>
        <InfoRow label="Status" value={hasProAccess(prefs) ? 'Active' : 'Free'} />
        {!hasProAccess(prefs) ? (
          <>
            <AppText variant="tiny" color="textFaint" style={{ marginTop: 6, lineHeight: 16 }}>
              1 rate alert included. Pro unlocks unlimited alerts, deep search, bank intelligence
              (rate-move feed, RBA pass-through, per-bank history), and the history ribbon.
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

      <Section title="Appearance">
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
      </Section>

      <Section title="Your interests">
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
      </Section>

      <Section title="Defaults">
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

      <Section title="Optional data">
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
          label="History ribbon chart"
          sub={hasProAccess(prefs) ? 'Charts & trends - compact history' : 'Pro'}
          value={effectiveHistoryRibbon(prefs)}
          onChange={onToggleHistoryRibbon}
        />
        {effectiveHistoryRibbon(prefs) ? (
          <Button
            title="View history ribbon"
            icon="stats-chart"
            variant="secondary"
            style={{ marginTop: 10 }}
            onPress={() => router.push('/(tabs)/trends' as Href)}
          />
        ) : null}
      </Section>

      <Section title="Notifications">
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

      <Section title="Data">
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

      <Section title="Diagnostics">
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

      <AppUpdateSection />

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

function AppUpdateSection() {
  const installed = getInstalledAppInfo();
  const [checkResult, setCheckResult] = useState<UpdateCheckResult | null>(null);
  const [remote, setRemote] = useState<ApkManifest | null>(null);
  const [changelogs, setChangelogs] = useState<VersionChangelogSummary[]>([]);
  const [checking, setChecking] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadPct, setDownloadPct] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [installAllowed, setInstallAllowed] = useState<boolean | null>(null);

  const refreshInstallPermission = useCallback(async () => {
    setInstallAllowed(await canInstallApkUpdates());
  }, []);

  useEffect(() => {
    void refreshInstallPermission();
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') void refreshInstallPermission();
    });
    return () => sub.remove();
  }, [refreshInstallPermission]);

  const onCheck = useCallback(async () => {
    setChecking(true);
    setError(null);
    setCheckResult(null);
    setChangelogs([]);
    try {
      const result = await checkForAppUpdate();
      setCheckResult(result);
      if (result.status === 'available' || result.status === 'current') {
        setRemote(result.remote);
      }
      if (result.status === 'available') {
        setChangelogs(result.changelogs);
      }
      if (result.status === 'error') {
        setError(result.message);
      }
    } finally {
      setChecking(false);
    }
  }, []);

  const onDownload = useCallback(async () => {
    if (!remote) return;
    const allowed = await ensureInstallPermission();
    if (!allowed) return;
    setDownloading(true);
    setError(null);
    setDownloadPct(null);
    try {
      await downloadAndInstallUpdate(remote, (progress) => {
        if (progress.totalBytes) {
          setDownloadPct(Math.round((progress.bytesWritten / progress.totalBytes) * 100));
        }
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      Alert.alert('Update failed', message);
    } finally {
      setDownloading(false);
    }
  }, [remote]);

  if (Platform.OS !== 'android') {
    return null;
  }

  const updateAvailable = checkResult?.status === 'available';
  const latestLabel = remote
    ? `${remote.version} (${remote.build_number})`
    : checkResult?.status === 'current'
      ? `${installed.version} (${installed.buildNumber})`
      : '—';

  return (
    <Section title="App update">
      <InfoRow label="Installed" value={`${installed.version} (${installed.buildNumber})`} />
      <InfoRow label="Latest" value={latestLabel} />
      <InfoRow
        label="Install permission"
        value={installAllowed === null ? '—' : installAllowed ? 'Allowed' : 'Required'}
      />
      {installAllowed === false ? (
        <Row gap={12} style={{ marginTop: 8 }}>
          <Button
            title="Allow app updates"
            icon="settings-outline"
            variant="secondary"
            style={{ flex: 1 }}
            onPress={() => void openInstallPermissionSettings()}
          />
        </Row>
      ) : null}
      {downloadPct !== null ? (
        <InfoRow label="Download" value={`${downloadPct}%`} />
      ) : null}
      {error ? (
        <AppText variant="tiny" color="danger" style={{ marginTop: 6 }}>
          {error}
        </AppText>
      ) : null}
      {updateAvailable && changelogs.length ? (
        <UpdateChangelogList entries={changelogs} />
      ) : null}
      <Row gap={12} style={{ marginTop: 12 }}>
        <Button
          title="Check for update"
          icon="cloud-download-outline"
          variant="secondary"
          style={{ flex: 1 }}
          loading={checking}
          disabled={downloading}
          onPress={() => void onCheck()}
        />
        {updateAvailable ? (
          <Button
            title="Download update"
            icon="download-outline"
            style={{ flex: 1 }}
            loading={downloading}
            disabled={checking}
            onPress={() => void onDownload()}
          />
        ) : null}
      </Row>
      <AppText variant="tiny" color="textFaint" style={{ marginTop: 8, lineHeight: 16 }}>
        Required to install updates from the app. Android keeps this setting across app updates for
        the same package and signing key.
      </AppText>
    </Section>
  );
}

function UpdateChangelogList({ entries }: { entries: VersionChangelogSummary[] }) {
  return (
    <View style={{ marginTop: 10, maxHeight: 220 }}>
      <AppText variant="small" weight="700" color="textMuted" style={{ marginBottom: 6 }}>
        WHAT&apos;S NEW
      </AppText>
      <ScrollView nestedScrollEnabled>
        {entries.map((entry) => (
          <View key={entry.version} style={{ marginBottom: 10 }}>
            <AppText variant="small" weight="700">
              {entry.version}
            </AppText>
            {entry.summaryBullets.map((bullet, idx) => (
              <AppText key={`${entry.version}-${idx}`} variant="tiny" color="textFaint" style={{ marginLeft: 8 }}>
                • {bullet}
              </AppText>
            ))}
            <Pressable onPress={() => void Linking.openURL(entry.releaseUrl)}>
              <AppText variant="tiny" color="primary" style={{ marginTop: 4 }}>
                Full changelog
              </AppText>
            </Pressable>
          </View>
        ))}
      </ScrollView>
    </View>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={{ marginBottom: 18 }}>
      <AppText variant="small" weight="700" color="textMuted" style={{ marginBottom: 8, marginLeft: 4 }}>
        {title.toUpperCase()}
      </AppText>
      <Card style={{ gap: 4 }}>{children}</Card>
    </View>
  );
}

function InterestOrderRow({
  title,
  canMoveUp,
  canMoveDown,
  canRemove,
  onMoveUp,
  onMoveDown,
  onRemove,
}: {
  title: string;
  canMoveUp: boolean;
  canMoveDown: boolean;
  canRemove: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
}) {
  return (
    <Row style={{ justifyContent: 'space-between', paddingVertical: 6 }}>
      <AppText variant="body" weight="600" style={{ flex: 1 }}>
        {title}
      </AppText>
      <Row gap={4}>
        <IconButton
          icon="chevron-up"
          onPress={onMoveUp}
          disabled={!canMoveUp}
          accessibilityLabel={`Move ${title} up`}
        />
        <IconButton
          icon="chevron-down"
          onPress={onMoveDown}
          disabled={!canMoveDown}
          accessibilityLabel={`Move ${title} down`}
        />
        <IconButton
          icon="close"
          onPress={onRemove}
          disabled={!canRemove}
          accessibilityLabel={`Remove ${title}`}
        />
      </Row>
    </Row>
  );
}

function Label({ text }: { text: string }) {
  return (
    <AppText variant="small" color="textMuted" style={{ marginBottom: 10 }}>
      {text}
    </AppText>
  );
}

function ToggleRow({
  icon,
  label,
  sub,
  value,
  onChange,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  sub?: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  const theme = useTheme();
  return (
    <Row gap={12} style={{ minHeight: TOUCH_TARGET_MIN }}>
      <Ionicons name={icon} size={20} color={theme.colors.primary} />
      <View style={{ flex: 1 }}>
        <AppText variant="body" weight="600">
          {label}
        </AppText>
        {sub ? (
          <AppText variant="tiny" color="textFaint">
            {sub}
          </AppText>
        ) : null}
      </View>
      <Switch
        value={value}
        onValueChange={onChange}
        trackColor={{ true: theme.colors.primary, false: theme.colors.border }}
      />
    </Row>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <Row style={{ justifyContent: 'space-between', paddingVertical: 5 }}>
      <AppText variant="small" color="textMuted">
        {label}
      </AppText>
      <AppText variant="small" weight="600">
        {value}
      </AppText>
    </Row>
  );
}
