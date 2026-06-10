import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { View } from 'react-native';

import { useNextIngestCountdown } from '../hooks/useNextIngestCountdown';
import { dataSourceLabel } from '../lib/nextIngest';
import type { PayloadSource } from '../types';
import { useTheme } from '../theme/ThemeProvider';
import { BrandLockup } from './BrandLockup';
import { AppText, Card, Row } from './ui';

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
  const sourceLabel = dataSourceLabel(source);
  const statusIcon = offline ? 'cloud-offline-outline' : source === 'remote' ? 'cloud-done' : 'albums-outline';
  const statusColor = offline ? theme.colors.warning : theme.colors.success;

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
          <AppText variant="tiny" color="textMuted" style={{ marginTop: 3 }}>
            {runDateLabel} · {runAgeLabel}
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

      <Row gap={8} style={{ marginTop: 10 }}>
        <StatPill label="Products" value={String(productCount)} />
        <StatPill label="Lenders" value={String(lenderCount)} />
        <StatPill label="In section" value={String(providerCount)} />
      </Row>
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

function StatPill({ label, value }: { label: string; value: string }) {
  const theme = useTheme();
  return (
    <View
      style={{
        flex: 1,
        backgroundColor: theme.colors.card,
        borderRadius: theme.radius.sm,
        borderWidth: 1,
        borderColor: theme.colors.border,
        paddingVertical: 8,
        paddingHorizontal: 6,
        alignItems: 'center',
      }}
    >
      <AppText variant="body" weight="800">
        {value}
      </AppText>
      <AppText variant="tiny" color="textMuted" weight="700" style={{ marginTop: 2, letterSpacing: 0.4 }}>
        {label}
      </AppText>
    </View>
  );
}
