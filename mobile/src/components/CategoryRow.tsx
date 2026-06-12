import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Pressable, View } from 'react-native';

import { SECTIONS } from '../constants';
import type { RateStats } from '../data/taxonomy';
import type { SectionKey } from '../types';
import { useTheme } from '../theme/ThemeProvider';
import { Ribbon } from './Ribbon';
import { AppText, Row } from './ui';

/** Shared taxonomy category row — Home shortcuts and Browse drill-down. */
export function CategoryRow({
  label,
  productCount,
  providerCount,
  rate,
  section,
  onPress,
  accent,
  showAccent = false,
  ribbonStats,
  ribbonDomain,
}: {
  label: string;
  productCount: number;
  providerCount: number;
  rate: number | null;
  section: SectionKey;
  onPress: () => void;
  accent?: string;
  showAccent?: boolean;
  ribbonStats?: RateStats;
  /** Shared scale across sibling rows so ranges are directly comparable. */
  ribbonDomain?: { min: number; max: number } | null;
}) {
  const theme = useTheme();
  const meta = SECTIONS[section];
  const chromeAccent = accent ?? meta.accentColor;
  const rateColor = meta.lowerIsBetter ? theme.colors.rateLoan : theme.colors.rateDeposit;
  const productLabel = productCount === 1 ? 'product' : 'products';

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        backgroundColor: theme.colors.card,
        borderRadius: theme.radius.lg,
        borderWidth: 1,
        borderColor: theme.colors.border,
        borderLeftWidth: showAccent ? 3 : 1,
        borderLeftColor: showAccent ? chromeAccent : theme.colors.border,
        padding: theme.spacing(4),
        opacity: pressed ? 0.85 : 1,
      })}
    >
      <Row
        style={{
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginBottom: ribbonStats ? theme.spacing(2) : 0,
        }}
      >
        <View style={{ flex: 1, paddingRight: theme.spacing(3) }}>
          <AppText variant="body" weight="700" numberOfLines={2}>
            {label}
          </AppText>
          <AppText variant="tiny" color="textFaint" style={{ marginTop: theme.spacing(1) / 2 }}>
            {productCount} {productLabel} · {providerCount} lenders
          </AppText>
        </View>
        <Row gap={theme.spacing(1)}>
          <AppText variant="h3" weight="800" style={{ color: rateColor }}>
            {rate !== null ? `${(rate * 100).toFixed(2)}%` : '—'}
          </AppText>
          <Ionicons name="chevron-forward" size={18} color={theme.colors.textFaint} />
        </Row>
      </Row>
      {ribbonStats ? <Ribbon stats={ribbonStats} section={section} compact domain={ribbonDomain} /> : null}
    </Pressable>
  );
}
