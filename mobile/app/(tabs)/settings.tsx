import { Ionicons } from '@expo/vector-icons';
import * as Application from 'expo-application';
import { useRouter, type Href } from 'expo-router';
import React, { useCallback, useState } from 'react';
import { Alert, Platform, Pressable, Switch, View } from 'react-native';

import { SegmentedControl } from '../../src/components/controls';
import { ScreenScrollView } from '../../src/components/Screen';
import { AppText, Button, Card, Chip, Divider, Row } from '../../src/components/ui';
import { SECTIONS, SECTION_ORDER } from '../../src/constants';
import { formatRunDate, relativeDate } from '../../src/data/format';
import {
  ensurePermissions,
  registerBackgroundRefresh,
  unregisterBackgroundRefresh,
} from '../../src/data/notifications';
import { useStore } from '../../src/data/store';
import {
  checkForAppUpdate,
  downloadAndInstallUpdate,
  getInstalledAppInfo,
  type ApkManifest,
  type UpdateCheckResult,
} from '../../src/lib/appUpdate';
import { setDiagnosticsEnabled } from '../../src/lib/observability';
import type { Subscription } from '../../src/data/subscriptions';
import type { ThemeMode } from '../../src/theme/theme';
import { dataSourceLabel } from '../../src/lib/nextIngest';
import { useTheme } from '../../src/theme/ThemeProvider';

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
  const theme = useTheme();

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
    <ScreenScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
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

      <Section title="Defaults">
        <Label text="Default category" />
        <Row gap={8} style={{ flexWrap: 'wrap' }}>
          {SECTION_ORDER.map((key) => (
            <Chip
              key={key}
              label={SECTIONS[key].title}
              selected={prefs.defaultSection === key}
              onPress={() => setPref('defaultSection', key)}
            />
          ))}
        </Row>
        <Divider style={{ marginVertical: 12 }} />
        <ToggleRow
          icon="analytics-outline"
          label="History ribbon chart"
          value={prefs.showHistoryRibbon}
          onChange={(v) => setPref('showHistoryRibbon', v)}
        />
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
                  onRemove={() => removeSubscription(sub.id)}
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
        <InfoRow label="Lenders" value={core ? String(Object.keys(core.brands).length) : '—'} />
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
        <Pressable
          onPress={() => router.push('/debug-log' as Href)}
          style={({ pressed }) => ({
            flexDirection: 'row',
            alignItems: 'center',
            gap: 12,
            paddingVertical: 6,
            opacity: pressed ? 0.7 : 1,
          })}
        >
          <Ionicons name="document-text-outline" size={20} color={theme.colors.primary} />
          <View style={{ flex: 1 }}>
            <AppText variant="body" weight="600">
              Debug log
            </AppText>
            <AppText variant="tiny" color="textFaint">
              View, share, or upload end-to-end logs
            </AppText>
          </View>
          <Ionicons name="chevron-forward" size={18} color={theme.colors.textMuted} />
        </Pressable>
      </Section>

      <AppUpdateSection />

      <Section title="About">
        <InfoRow
          label="Version"
          value={`${Application.nativeApplicationVersion ?? '1.0.0'} (${Application.nativeBuildVersion ?? '0'})`}
        />
        <AppText variant="tiny" color="textFaint" style={{ marginTop: 12, lineHeight: 16 }}>
          Rates are sourced from public Consumer Data Right (open banking) product data and
          provided for general information only — not financial advice. Always confirm with the
          lender before applying.
        </AppText>
      </Section>
    </ScreenScrollView>
  );
}

function AppUpdateSection() {
  const installed = getInstalledAppInfo();
  const [checkResult, setCheckResult] = useState<UpdateCheckResult | null>(null);
  const [remote, setRemote] = useState<ApkManifest | null>(null);
  const [checking, setChecking] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadPct, setDownloadPct] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onCheck = useCallback(async () => {
    setChecking(true);
    setError(null);
    setCheckResult(null);
    try {
      const result = await checkForAppUpdate();
      setCheckResult(result);
      if (result.status === 'available' || result.status === 'current') {
        setRemote(result.remote);
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
      {downloadPct !== null ? (
        <InfoRow label="Download" value={`${downloadPct}%`} />
      ) : null}
      {error ? (
        <AppText variant="tiny" color="danger" style={{ marginTop: 6 }}>
          {error}
        </AppText>
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
        Preview builds are published on the release channel. Android will prompt to install; allow
        installs from this app if prompted.
      </AppText>
    </Section>
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
    <Row gap={12}>
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

function SubscriptionRow({
  kind,
  label,
  onRemove,
}: {
  kind: 'Product' | 'Search';
  label: string;
  onRemove: () => void;
}) {
  const theme = useTheme();
  return (
    <Pressable
      onPress={onRemove}
      style={({ pressed }) => ({
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        paddingVertical: 8,
        opacity: pressed ? 0.7 : 1,
      })}
    >
      <View style={{ flex: 1 }}>
        <AppText variant="tiny" color="textFaint">
          {kind}
        </AppText>
        <AppText variant="small" weight="600">
          {label}
        </AppText>
      </View>
      <Ionicons name="close-circle-outline" size={20} color={theme.colors.textMuted} />
    </Pressable>
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
