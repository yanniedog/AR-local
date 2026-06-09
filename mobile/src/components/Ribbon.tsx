import React, { useState } from 'react';
import { useWindowDimensions, View } from 'react-native';
import Svg, { Circle, Defs, Line, LinearGradient, Rect, Stop, Text as SvgText } from 'react-native-svg';

import { SECTIONS } from '../constants';
import { formatRate } from '../data/format';
import type { RateStats } from '../data/taxonomy';
import type { SectionKey } from '../types';
import { useTheme } from '../theme/ThemeProvider';
import { AppText, Row } from './ui';

/**
 * The AR-local "ribbon": a rate-distribution bar (min..max) with median + mean
 * markers, coloured by section direction (green = best end). Optionally overlays
 * the RBA cash rate for home loans.
 */
export function Ribbon({
  stats,
  section,
  rbaRate,
  compact,
}: {
  stats: RateStats;
  section: SectionKey;
  rbaRate?: number | null;
  compact?: boolean;
}) {
  const theme = useTheme();
  const { width: screenW } = useWindowDimensions();
  const [w, setW] = useState(0);
  // FlashList headers and first paint can report 0 width — fall back so the bar renders.
  const layoutW = w > 0 ? w : Math.max(1, screenW - 64);
  // Unique per instance — multiple ribbons render on one screen and SVG ids must not
  // collide. Must be before any early return (rules-of-hooks).
  const gradId = `grad-${React.useId().replace(/:/g, '')}`;
  const { min, max, median, mean } = stats;
  const lowerIsBetter = SECTIONS[section].lowerIsBetter;

  if (min === null || max === null) {
    return (
      <AppText variant="small" color="textFaint">
        No rate data
      </AppText>
    );
  }

  const h = compact ? 30 : 44;
  const barY = compact ? 8 : 14;
  const barH = compact ? 10 : 14;
  const pad = 2;
  const span = max - min || 1;
  const x = (v: number) => pad + ((v - min) / span) * (Math.max(1, layoutW) - 2 * pad);

  const goodColor = theme.colors.success;
  const badColor = theme.colors.danger;
  const leftColor = lowerIsBetter ? goodColor : badColor;
  const rightColor = lowerIsBetter ? badColor : goodColor;
  const rba = rbaRate != null ? rbaRate / 100 : null;
  const rbaIn = rba != null && rba >= min && rba <= max;

  return (
    <View>
      <View onLayout={(e) => setW(e.nativeEvent.layout.width)} style={{ width: '100%', height: h }}>
        <Svg width={layoutW} height={h}>
            <Defs>
              <LinearGradient id={gradId} x1="0" y1="0" x2="1" y2="0">
                <Stop offset="0" stopColor={leftColor} stopOpacity={0.85} />
                <Stop offset="0.5" stopColor={theme.colors.warning} stopOpacity={0.8} />
                <Stop offset="1" stopColor={rightColor} stopOpacity={0.85} />
              </LinearGradient>
            </Defs>
            <Rect x={pad} y={barY} width={Math.max(1, layoutW - 2 * pad)} height={barH} rx={barH / 2} fill={`url(#${gradId})`} />
            {/* mean marker (thin) */}
            {mean !== null ? (
              <Line x1={x(mean)} y1={barY - 3} x2={x(mean)} y2={barY + barH + 3} stroke={theme.colors.text} strokeWidth={1.5} />
            ) : null}
            {/* median marker (dot) */}
            {median !== null ? (
              <Circle cx={x(median)} cy={barY + barH / 2} r={barH / 2 + 1} fill={theme.colors.surface} stroke={theme.colors.text} strokeWidth={2} />
            ) : null}
            {/* RBA cash-rate marker for loans */}
            {rbaIn ? (
              <>
                <Line x1={x(rba!)} y1={barY - 5} x2={x(rba!)} y2={barY + barH + 5} stroke={theme.colors.primary} strokeWidth={2} strokeDasharray="2,2" />
                {!compact ? (
                  <SvgText x={x(rba!)} y={barY + barH + 14} fontSize={9} fill={theme.colors.primary} textAnchor="middle">
                    RBA
                  </SvgText>
                ) : null}
              </>
            ) : null}
          </Svg>
      </View>
      <Row style={{ justifyContent: 'space-between', marginTop: 2 }}>
        <Stat label="Min" value={formatRate(min)} color={leftColor} />
        <Stat label="Median" value={formatRate(median)} align="center" />
        {!compact ? <Stat label="Mean" value={formatRate(mean)} align="center" /> : null}
        <Stat label="Max" value={formatRate(max)} align="right" color={rightColor} />
      </Row>
      {!compact ? (
        <AppText variant="tiny" color="textFaint" style={{ marginTop: 4 }}>
          {stats.count} rates · {stats.providers} lenders
        </AppText>
      ) : null}
    </View>
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
