import { Ionicons } from '@expo/vector-icons';
import React, { useState } from 'react';
import { Pressable, View } from 'react-native';

import type { PayloadProgressSnapshot } from '../data/downloadProgress';
import {
  computeEtaSeconds,
  computePercent,
  computeTransferRate,
  formatEta,
  formatTransferRate,
  phaseLabel,
} from '../data/downloadProgress';
import { useStore } from '../data/store';
import { useTheme } from '../theme/ThemeProvider';
import { resolveOfflineBanner } from './bannerState';
import { AppText, Row } from './ui';

/** Collapsible live transfer metrics — collapsed by default. */
export function PayloadProgressDetails({ progress }: { progress: PayloadProgressSnapshot }) {
  const theme = useTheme();
  const [expanded, setExpanded] = useState(false);
  const rate = computeTransferRate(progress.bytesReceived, progress.startedAt);
  const pct = computePercent(progress.bytesReceived, progress.totalBytes);
  const eta = computeEtaSeconds(progress.bytesReceived, progress.totalBytes, rate);
  const showTransfer = progress.phase === 'manifest' || progress.phase === 'download';

  return (
    <View style={{ flex: 1 }}>
      <Row gap={6}>
        <AppText variant="small" color="textMuted" style={{ flex: 1 }}>
          Showing bundled sample data — connecting for the latest…
        </AppText>
        <Pressable
          onPress={() => setExpanded((v) => !v)}
          hitSlop={8}
          accessibilityRole="button"
          accessibilityLabel={expanded ? 'Hide download progress' : 'Show download progress'}
        >
          <Ionicons
            name={expanded ? 'chevron-up' : 'chevron-down'}
            size={14}
            color={theme.colors.textMuted}
          />
        </Pressable>
      </Row>
      {expanded ? (
        <View style={{ marginTop: 6, gap: 2 }}>
          <AppText variant="tiny" color="textMuted" numberOfLines={1}>
            File: {progress.fileName}
          </AppText>
          {showTransfer ? (
            <>
              <AppText variant="tiny" color="textMuted">
                Rate: {formatTransferRate(rate)}
              </AppText>
              <AppText variant="tiny" color="textMuted">
                Done: {pct != null ? `${pct}%` : '—'}
              </AppText>
              <AppText variant="tiny" color="textMuted">
                ETA: {formatEta(eta)}
              </AppText>
            </>
          ) : (
            <AppText variant="tiny" color="textMuted">
              Step: {phaseLabel(progress.phase)}
            </AppText>
          )}
        </View>
      ) : null}
    </View>
  );
}

export function OfflineBanner({ source, offline }: { source: string; offline: boolean }) {
  const theme = useTheme();
  const payloadProgress = useStore((s) => s.payloadProgress);
  const refreshing = useStore((s) => s.refreshing);
  const banner = resolveOfflineBanner(source, offline, refreshing, payloadProgress);
  if (banner.mode === 'hidden') return null;
  const sample = banner.mode === 'connecting' || banner.mode === 'offline-sample';
  return (
    <Row
      gap={8}
      style={{
        backgroundColor: sample ? theme.colors.primaryMuted : theme.colors.chip,
        paddingHorizontal: 12,
        paddingVertical: 8,
        borderRadius: theme.radius.md,
        marginBottom: 12,
        alignItems: banner.showLiveProgress ? 'flex-start' : 'center',
      }}
    >
      <Ionicons
        name={sample ? 'flask-outline' : 'cloud-offline-outline'}
        size={16}
        color={sample ? theme.colors.primary : theme.colors.warning}
        style={banner.showLiveProgress ? { marginTop: 2 } : undefined}
      />
      {banner.showLiveProgress && payloadProgress ? (
        <PayloadProgressDetails progress={payloadProgress} />
      ) : (
        <AppText variant="small" color="textMuted" style={{ flex: 1 }}>
          {banner.message}
        </AppText>
      )}
    </Row>
  );
}

export function EmptyState({
  icon = 'search',
  title,
  subtitle,
  fill,
}: {
  icon?: keyof typeof Ionicons.glyphMap;
  title: string;
  subtitle?: string;
  /** When true, fills the screen with the themed background (tab empty states). */
  fill?: boolean;
}) {
  const theme = useTheme();
  return (
    <View
      style={[
        { alignItems: 'center', paddingVertical: 48, paddingHorizontal: 24 },
        fill && { flex: 1, backgroundColor: theme.colors.bg, justifyContent: 'center' },
      ]}
    >
      <Ionicons name={icon} size={42} color={theme.colors.textFaint} />
      <AppText variant="h3" style={{ marginTop: 12, textAlign: 'center' }}>
        {title}
      </AppText>
      {subtitle ? (
        <AppText variant="small" color="textMuted" style={{ marginTop: 6, textAlign: 'center' }}>
          {subtitle}
        </AppText>
      ) : null}
    </View>
  );
}

export function LoadingRows({ count = 6 }: { count?: number }) {
  const theme = useTheme();
  return (
    <View>
      {Array.from({ length: count }).map((_, i) => (
        <View
          key={i}
          style={{
            height: 76,
            borderRadius: theme.radius.lg,
            backgroundColor: theme.colors.skeleton,
            marginBottom: 10,
          }}
        />
      ))}
    </View>
  );
}
