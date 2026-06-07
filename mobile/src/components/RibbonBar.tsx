import React from 'react';
import { View } from 'react-native';

import type { Ribbon, SectionKey } from '../types';
import { formatRate } from '../data/format';
import { useTheme } from '../theme/ThemeProvider';
import { AppText, Row } from './ui';

/** A min..max distribution track with median + mean markers. */
export function RibbonBar({ ribbon, section }: { ribbon: Ribbon; section: SectionKey }) {
  const theme = useTheme();
  const { min, max, mean, median } = ribbon.range;
  if (min === null || max === null || max <= min) {
    return null;
  }
  const span = max - min;
  const pct = (v: number | null) => (v === null ? 0 : Math.max(0, Math.min(1, (v - min) / span)) * 100);

  return (
    <View>
      <Row style={{ justifyContent: 'space-between', marginBottom: 8 }}>
        <Stat label="Min" value={formatRate(min)} color={theme.colors.success} />
        <Stat label="Median" value={formatRate(median)} align="center" />
        <Stat label="Mean" value={formatRate(mean)} align="center" />
        <Stat label="Max" value={formatRate(max)} align="right" color={theme.colors.danger} />
      </Row>
      <View
        style={{
          height: 10,
          borderRadius: 999,
          backgroundColor: theme.colors.surfaceAlt,
          overflow: 'hidden',
        }}
      >
        <View
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            top: 0,
            bottom: 0,
            backgroundColor: theme.colors.primaryMuted,
          }}
        />
        {median !== null ? (
          <Marker left={pct(median)} color={theme.colors.primary} />
        ) : null}
        {mean !== null ? <Marker left={pct(mean)} color={theme.colors.text} thin /> : null}
      </View>
      <AppText variant="tiny" color="textFaint" style={{ marginTop: 6 }}>
        {ribbon.counts.products} products · {ribbon.counts.providers} lenders ·{' '}
        {ribbon.counts.rates} rates
      </AppText>
    </View>
  );
}

function Marker({ left, color, thin }: { left: number; color: string; thin?: boolean }) {
  return (
    <View
      style={{
        position: 'absolute',
        left: `${left}%`,
        top: 0,
        bottom: 0,
        width: thin ? 2 : 3,
        marginLeft: thin ? -1 : -1.5,
        backgroundColor: color,
      }}
    />
  );
}

function Stat({
  label,
  value,
  align = 'left',
  color,
}: {
  label: string;
  value: string;
  align?: 'left' | 'center' | 'right';
  color?: string;
}) {
  return (
    <View style={{ alignItems: align === 'left' ? 'flex-start' : align === 'right' ? 'flex-end' : 'center' }}>
      <AppText variant="tiny" color="textFaint">
        {label}
      </AppText>
      <AppText variant="small" weight="700" style={color ? { color } : undefined}>
        {value}
      </AppText>
    </View>
  );
}
