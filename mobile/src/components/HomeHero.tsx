import { Ionicons } from '@expo/vector-icons';
import React, { useEffect, type ReactNode } from 'react';
import { Pressable, View } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withSpring } from 'react-native-reanimated';

import { useNextIngestCountdown } from '../hooks/useNextIngestCountdown';
import { dataSourceLabel } from '../lib/nextIngest';
import type { PayloadSource } from '../types';
import { useTheme } from '../theme/ThemeProvider';
import { BrandLockup } from './BrandLockup';
import { AppText, Card, Row } from './ui';

const SPRING = { damping: 14, stiffness: 180, mass: 0.8 };

/** Spring scale wrapper for hero stats / ribbon when `dataKey` changes (new payload). */
export function SpringOnNewData({
  dataKey,
  children,
}: {
  dataKey: string;
  children: ReactNode;
}) {
  const scale = useSharedValue(1);

  useEffect(() => {
    scale.value = 0.94;
    scale.value = withSpring(1, SPRING);
  }, [dataKey, scale]);

  const style = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  return <Animated.View style={style}>{children}</Animated.View>;
}

export function HomeHero({
  runDateLabel,
  runAgeLabel,
  source,
  offline,
  productCount,
  lenderCount,
  providerCount,
  dataKey,
  onLendersPress,
}: {
  runDateLabel: string;
  runAgeLabel: string;
  source: PayloadSource;
  offline: boolean;
  productCount: number;
  lenderCount: number;
  providerCount: number;
  /** Changes when a new payload is installed — drives spring motion. */
  dataKey: string;
  onLendersPress?: () => void;
}) {
  const theme = useTheme();
  const sourceLabel = dataSourceLabel(source);
  const statusIcon = offline ? 'cloud-offline-outline' : source === 'remote' ? 'cloud-done' : 'albums-outline';
  const statusColor = offline ? theme.colors.warning : theme.colors.success;
  const statsKey = `${dataKey}:${productCount}:${lenderCount}:${providerCount}`;
  const datePulse = useSharedValue(1);

  useEffect(() => {
    datePulse.value = 0.92;
    datePulse.value = withSpring(1, SPRING);
  }, [dataKey, datePulse]);

  const dateStyle = useAnimatedStyle(() => ({
    transform: [{ scale: datePulse.value }],
  }));

  return (
    <View
      style={{
        backgroundColor: theme.colors.surface,
        borderRadius: theme.radius.md,
        borderWidth: 1,
        borderColor: theme.colors.border,
        padding: 12,
        marginBottom: 12,
        overflow: 'hidden',
      }}
    >
      <Row style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <View style={{ flex: 1, paddingRight: 8 }}>
          <BrandLockup markSize={28} style={{ marginBottom: 6 }} />
          <AppText
            variant="tiny"
            color="textMuted"
            weight="700"
            style={{ letterSpacing: 1.4, textTransform: 'uppercase', marginBottom: 2 }}
          >
            Daily rates
          </AppText>
          <AppText variant="h2" weight="800" style={{ lineHeight: 28 }}>
            Home loan rates, tracked.
          </AppText>
          <Animated.View style={dateStyle}>
            <AppText variant="tiny" color="textMuted" style={{ marginTop: 3 }}>
              {runDateLabel} · {runAgeLabel}
            </AppText>
          </Animated.View>
        </View>
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: 6,
            backgroundColor: theme.colors.chip,
            paddingHorizontal: 10,
            paddingVertical: 6,
            borderRadius: theme.radius.sm,
            borderWidth: 1,
            borderColor: theme.colors.border,
          }}
        >
          <Ionicons name={statusIcon} size={14} color={statusColor} />
          <AppText variant="tiny" weight="700" color="chipText">
            {offline ? 'Offline' : sourceLabel}
          </AppText>
        </View>
      </Row>

      <SpringOnNewData dataKey={statsKey}>
        <Row gap={8} style={{ marginTop: 10 }}>
          <StatPill label="Products" value={String(productCount)} />
          <StatPill
            label="Lenders"
            value={String(lenderCount)}
            onPress={onLendersPress}
            accessibilityLabel={`${lenderCount} lenders`}
            accessibilityHint={onLendersPress ? 'Opens lender directory' : undefined}
          />
          <StatPill label="In section" value={String(providerCount)} />
        </Row>
      </SpringOnNewData>
    </View>
  );
}

/** Below-fold refresh timing — kept out of the compact hero for progressive disclosure. */
export function HomeRefreshCountdown() {
  const theme = useTheme();
  const countdown = useNextIngestCountdown();

  return (
    <Card style={{ marginBottom: 12 }}>
      <Row gap={8} style={{ alignItems: 'flex-start' }}>
        <Ionicons name="time-outline" size={18} color={theme.colors.primary} style={{ marginTop: 1 }} />
        <View style={{ flex: 1 }}>
          <AppText variant="tiny" color="textMuted" weight="600" style={{ letterSpacing: 0.6 }}>
            NEXT DATA REFRESH
          </AppText>
          <AppText variant="h3" weight="800" style={{ color: theme.colors.primary, marginTop: 2 }}>
            {countdown.countdownLabel}
          </AppText>
          <AppText variant="tiny" color="textFaint" style={{ marginTop: 4 }}>
            Target {countdown.nextDueLocalLabel} · scheduled daily refresh
          </AppText>
        </View>
      </Row>
    </Card>
  );
}

function StatPill({
  label,
  value,
  onPress,
  accessibilityLabel,
  accessibilityHint,
}: {
  label: string;
  value: string;
  onPress?: () => void;
  accessibilityLabel?: string;
  accessibilityHint?: string;
}) {
  const theme = useTheme();
  const style = {
    flex: 1 as const,
    backgroundColor: theme.colors.card,
    borderRadius: theme.radius.sm,
    borderWidth: 1,
    borderColor: theme.colors.border,
    paddingVertical: 8,
    paddingHorizontal: 6,
    alignItems: 'center' as const,
  };

  const content = (
    <>
      <AppText variant="body" weight="800">
        {value}
      </AppText>
      <AppText variant="tiny" color="textMuted" weight="700" style={{ marginTop: 2, letterSpacing: 0.4 }}>
        {label}
      </AppText>
    </>
  );

  if (!onPress) {
    return <View style={style}>{content}</View>;
  }

  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityHint={accessibilityHint}
      style={({ pressed }) => [style, { opacity: pressed ? 0.85 : 1 }]}
    >
      {content}
    </Pressable>
  );
}
