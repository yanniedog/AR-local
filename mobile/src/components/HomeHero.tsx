import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { View } from 'react-native';

import { useNextIngestCountdown } from '../hooks/useNextIngestCountdown';
import { dataSourceLabel } from '../lib/nextIngest';
import type { PayloadSource } from '../types';
import { useTheme } from '../theme/ThemeProvider';
import { AppText, Row } from './ui';

export function HomeHero({
  runDateLabel,
  runAgeLabel,
  source,
  offline,
  productCount,
  lenderCount,
  providerCount,
}: {
  runDateLabel: string;
  runAgeLabel: string;
  source: PayloadSource;
  offline: boolean;
  productCount: number;
  lenderCount: number;
  providerCount: number;
}) {
  const theme = useTheme();
  const countdown = useNextIngestCountdown();
  const sourceLabel = dataSourceLabel(source);
  const statusIcon = offline ? 'cloud-offline-outline' : source === 'remote' ? 'cloud-done' : 'albums-outline';
  const statusColor = offline ? theme.colors.warning : theme.colors.success;

  return (
    <View
      style={{
        backgroundColor: theme.colors.surface,
        borderRadius: theme.radius.xl,
        borderWidth: 1,
        borderColor: theme.colors.border,
        padding: 16,
        marginBottom: 14,
        overflow: 'hidden',
      }}
    >
      <View
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          bottom: 0,
          width: 4,
          backgroundColor: theme.colors.primary,
          borderTopLeftRadius: theme.radius.xl,
          borderBottomLeftRadius: theme.radius.xl,
        }}
      />
      <Row style={{ justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <View style={{ flex: 1, paddingRight: 8 }}>
          <AppText variant="h1" style={{ marginBottom: 4 }}>
            Australian Rates
          </AppText>
          <AppText variant="small" color="textMuted">
            Data set {runDateLabel} · {runAgeLabel}
          </AppText>
        </View>
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: 6,
            backgroundColor: theme.colors.chip,
            paddingHorizontal: 10,
            paddingVertical: 6,
            borderRadius: theme.radius.pill,
          }}
        >
          <Ionicons name={statusIcon} size={14} color={statusColor} />
          <AppText variant="tiny" weight="700" color="chipText">
            {offline ? 'Offline' : sourceLabel}
          </AppText>
        </View>
      </Row>

      <View
        style={{
          backgroundColor: theme.colors.primaryMuted,
          borderRadius: theme.radius.md,
          padding: 12,
          marginBottom: 12,
        }}
      >
        <Row gap={8} style={{ alignItems: 'flex-start' }}>
          <Ionicons name="time-outline" size={18} color={theme.colors.primary} style={{ marginTop: 1 }} />
          <View style={{ flex: 1 }}>
            <AppText variant="tiny" color="textMuted" weight="600">
              NEXT DATA REFRESH
            </AppText>
            <AppText variant="h2" weight="800" style={{ color: theme.colors.primary, marginTop: 2 }}>
              {countdown.countdownLabel}
            </AppText>
            <AppText variant="tiny" color="textFaint" style={{ marginTop: 4 }}>
              Target {countdown.nextDueLocalLabel} · scheduled daily refresh
            </AppText>
          </View>
        </Row>
      </View>

      <Row gap={8}>
        <StatPill label="Products" value={String(productCount)} />
        <StatPill label="Lenders" value={String(lenderCount)} />
        <StatPill label="In section" value={String(providerCount)} />
      </Row>
    </View>
  );
}

function StatPill({ label, value }: { label: string; value: string }) {
  const theme = useTheme();
  return (
    <View
      style={{
        flex: 1,
        backgroundColor: theme.colors.card,
        borderRadius: theme.radius.md,
        borderWidth: 1,
        borderColor: theme.colors.border,
        paddingVertical: 10,
        paddingHorizontal: 8,
        alignItems: 'center',
      }}
    >
      <AppText variant="h3" weight="800">
        {value}
      </AppText>
      <AppText variant="tiny" color="textFaint" style={{ marginTop: 2 }}>
        {label}
      </AppText>
    </View>
  );
}
