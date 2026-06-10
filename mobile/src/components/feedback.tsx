import { Ionicons } from '@expo/vector-icons';
import { useBottomTabBarHeight } from '@react-navigation/bottom-tabs';
import { router } from 'expo-router';
import React, { useEffect, useRef, useState } from 'react';
import { Animated as RNAnimated, Pressable, View, type DimensionValue, type ViewStyle } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Animated, {
  Easing,
  interpolate,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';

import type { PayloadProgressSnapshot } from '../data/downloadProgress';
import {
  computeEtaSeconds,
  computePercent,
  computeTransferRate,
  formatEta,
  formatTransferRate,
  phaseLabel,
} from '../data/downloadProgress';
import { formatRunDate } from '../data/format';
import { useStore } from '../data/store';
import { useTheme } from '../theme/ThemeProvider';
import { resolveOfflineBanner, resolveRefreshOutcomeSnackbar } from './bannerState';
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

/** Global data-health strip — same logic as {@link OfflineBanner}. */
export const DataHealthBanner = OfflineBanner;

const SNACKBAR_DISMISS_MS: Record<'success' | 'failure' | 'wifi-skip', number> = {
  success: 3500,
  failure: 7000,
  'wifi-skip': 5000,
};

/** Bottom snackbar for refresh success, failure, or Wi-Fi-only skip. Mount once per tab layout. */
export function RefreshOutcomeSnackbar() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const tabBarHeight = useBottomTabBarHeight();
  const outcome = useStore((s) => s.refreshOutcome);
  const core = useStore((s) => s.core);
  const clearRefreshOutcome = useStore((s) => s.clearRefreshOutcome);
  const refresh = useStore((s) => s.refresh);
  const opacity = useRef(new RNAnimated.Value(0)).current;
  const translateY = useRef(new RNAnimated.Value(12)).current;

  const model = outcome ? resolveRefreshOutcomeSnackbar(outcome, formatRunDate(core?.run_date)) : null;

  useEffect(() => {
    if (!outcome) return;
    opacity.setValue(0);
    translateY.setValue(12);
    RNAnimated.parallel([
      RNAnimated.timing(opacity, { toValue: 1, duration: 180, useNativeDriver: true }),
      RNAnimated.timing(translateY, { toValue: 0, duration: 180, useNativeDriver: true }),
    ]).start();
    const timer = setTimeout(() => clearRefreshOutcome(), SNACKBAR_DISMISS_MS[outcome]);
    return () => clearTimeout(timer);
  }, [outcome, clearRefreshOutcome, opacity, translateY]);

  if (!model) return null;

  const iconName =
    model.kind === 'success'
      ? 'checkmark-circle'
      : model.kind === 'failure'
        ? 'cloud-offline-outline'
        : 'wifi-outline';
  const iconColor =
    model.kind === 'success'
      ? theme.colors.success
      : model.kind === 'failure'
        ? theme.colors.warning
        : theme.colors.primary;

  const onAction = () => {
    clearRefreshOutcome();
    if (model.action === 'retry') void refresh({ manual: true, force: true });
    if (model.action === 'settings') router.push('/settings');
  };

  return (
    <RNAnimated.View
      pointerEvents="box-none"
      style={{
        position: 'absolute',
        left: 16,
        right: 16,
        bottom: insets.bottom + tabBarHeight + 8,
        opacity,
        transform: [{ translateY }],
        zIndex: 100,
      }}
    >
      <Row
        gap={10}
        style={{
          backgroundColor: theme.colors.surface,
          borderRadius: theme.radius.lg,
          borderWidth: 1,
          borderColor: theme.colors.border,
          paddingHorizontal: 14,
          paddingVertical: 12,
          alignItems: 'center',
          shadowColor: '#000',
          shadowOpacity: 0.12,
          shadowRadius: 8,
          shadowOffset: { width: 0, height: 2 },
          elevation: 4,
        }}
      >
        <Ionicons name={iconName} size={18} color={iconColor} />
        <AppText variant="small" style={{ flex: 1 }}>
          {model.message}
        </AppText>
        {model.actionLabel ? (
          <Pressable
            onPress={onAction}
            hitSlop={8}
            accessibilityRole="button"
            accessibilityLabel={model.actionLabel}
          >
            <AppText variant="small" weight="700" style={{ color: theme.colors.primary }}>
              {model.actionLabel}
            </AppText>
          </Pressable>
        ) : (
          <Pressable
            onPress={() => clearRefreshOutcome()}
            hitSlop={8}
            accessibilityRole="button"
            accessibilityLabel="Dismiss"
          >
            <Ionicons name="close" size={18} color={theme.colors.textMuted} />
          </Pressable>
        )}
      </Row>
    </RNAnimated.View>
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

const SHIMMER_SWEEP = 120;

function ShimmerBox({
  height,
  width = '100%',
  borderRadius,
  style,
}: {
  height: number;
  width?: DimensionValue;
  borderRadius: number;
  style?: ViewStyle;
}) {
  const theme = useTheme();
  const progress = useSharedValue(0);
  const trackWidth = useSharedValue(0);

  useEffect(() => {
    progress.value = withRepeat(
      withTiming(1, { duration: 1500, easing: Easing.linear }),
      -1,
      false,
    );
  }, [progress]);

  const shineStyle = useAnimatedStyle(() => ({
    transform: [
      {
        translateX: interpolate(
          progress.value,
          [0, 1],
          [-SHIMMER_SWEEP, Math.max(trackWidth.value, SHIMMER_SWEEP)],
        ),
      },
    ],
  }));

  const shineColor = theme.dark ? 'rgba(255,255,255,0.09)' : 'rgba(255,255,255,0.55)';

  return (
    <View
      onLayout={(e) => {
        trackWidth.value = e.nativeEvent.layout.width;
      }}
      style={[
        {
          height,
          width,
          borderRadius,
          backgroundColor: theme.colors.skeleton,
          overflow: 'hidden',
        },
        style,
      ]}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    >
      <Animated.View
        style={[
          {
            position: 'absolute',
            top: 0,
            bottom: 0,
            width: SHIMMER_SWEEP,
            backgroundColor: shineColor,
          },
          shineStyle,
        ]}
      />
    </View>
  );
}

function ProductCardSkeleton() {
  const theme = useTheme();
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingVertical: 12,
        paddingHorizontal: 14,
        backgroundColor: theme.colors.card,
        borderRadius: theme.radius.lg,
        borderWidth: 1,
        borderColor: theme.colors.border,
        marginBottom: 10,
      }}
    >
      <ShimmerBox height={44} width={44} borderRadius={22} />
      <View style={{ flex: 1, gap: 8 }}>
        <ShimmerBox height={14} width="72%" borderRadius={theme.radius.sm} />
        <ShimmerBox height={12} width="48%" borderRadius={theme.radius.sm} />
      </View>
      <ShimmerBox height={20} width={56} borderRadius={theme.radius.sm} />
    </View>
  );
}

/** Product-card-shaped shimmer placeholders for lists and browse remounts. */
export function LoadingRows({ count = 6 }: { count?: number }) {
  return (
    <View accessibilityRole="progressbar" accessibilityLabel="Loading content">
      {Array.from({ length: count }).map((_, i) => (
        <ProductCardSkeleton key={i} />
      ))}
    </View>
  );
}

const DETAIL_LINE_WIDTHS: DimensionValue[] = ['68%', '52%', '44%'];

/** Compact shimmer lines for product detail groups. */
export function DetailLoadingLines({ lines = 3 }: { lines?: number }) {
  const theme = useTheme();
  return (
    <View
      style={{ gap: 10 }}
      accessibilityRole="progressbar"
      accessibilityLabel="Loading product details"
    >
      {Array.from({ length: lines }).map((_, i) => (
        <ShimmerBox
          key={i}
          height={14}
          width={DETAIL_LINE_WIDTHS[i % DETAIL_LINE_WIDTHS.length]}
          borderRadius={theme.radius.sm}
        />
      ))}
    </View>
  );
}
