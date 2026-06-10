import React, { useEffect, useRef, useState } from 'react';
import { useWindowDimensions, View } from 'react-native';
import Animated, {
  Easing,
  useAnimatedProps,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';
import Svg, { Circle, Defs, Line, LinearGradient, Rect, Stop, Text as SvgText } from 'react-native-svg';

import { SECTIONS } from '../constants';
import { formatRate } from '../data/format';
import type { RateStats } from '../data/taxonomy';
import { ribbonA11ySummary } from '../lib/a11ySummaries';
import type { SectionKey } from '../types';
import type { Palette } from '../theme/colors';
import { useTheme } from '../theme/ThemeProvider';
import { AppText, Row } from './ui';

const AnimatedRect = Animated.createAnimatedComponent(Rect);
const AnimatedLine = Animated.createAnimatedComponent(Line);

const DRAW_MS = 720;

function useFirstMountDrawIn(duration = DRAW_MS) {
  const progress = useSharedValue(0);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    progress.value = withTiming(1, { duration, easing: Easing.out(Easing.cubic) });
  }, [duration, progress]);
  return progress;
}

/** Section-aware rate ink: loans use success, deposits use primary (rateDeposit role). */
function sectionFillColor(lowerIsBetter: boolean, colors: Palette) {
  return lowerIsBetter ? colors.success : colors.primary;
}

/**
 * The AR-local "ribbon": a rate-distribution bar (min..max) with median + mean
 * markers on a neutral track with muted section tint. Optionally overlays
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
  const drawProgress = useFirstMountDrawIn();
  const layoutW = w > 0 ? w : Math.max(1, screenW - 64);
  const fillGradId = `ribbon-fill-${React.useId().replace(/:/g, '')}`;
  const { min, max, median, mean } = stats;
  const lowerIsBetter = SECTIONS[section].lowerIsBetter;

  const h = compact ? 30 : 44;
  const barY = compact ? 8 : 14;
  const barH = compact ? 10 : 14;
  const pad = 2;
  const tickW = 4;
  const barW = Math.max(1, layoutW - 2 * pad);
  const meanLineLen = h + 6;
  const rbaLineLen = h + 10;

  const barAnimatedProps = useAnimatedProps(() => ({
    width: Math.max(1, barW * drawProgress.value),
  }));

  const rightTickAnimatedProps = useAnimatedProps(() => ({
    x: pad + Math.max(tickW, barW * drawProgress.value) - tickW,
  }));

  const meanAnimatedProps = useAnimatedProps(() => ({
    strokeDashoffset: meanLineLen * (1 - drawProgress.value),
  }));

  const rbaAnimatedProps = useAnimatedProps(() => ({
    strokeDashoffset: rbaLineLen * (1 - drawProgress.value),
  }));

  if (min === null || max === null) {
    return (
      <AppText variant="small" color="textFaint">
        No rate data
      </AppText>
    );
  }

  const span = max - min || 1;
  const x = (v: number) => pad + ((v - min) / span) * barW;

  const goodColor = theme.colors.success;
  const badColor = theme.colors.danger;
  const leftColor = lowerIsBetter ? goodColor : badColor;
  const rightColor = lowerIsBetter ? badColor : goodColor;
  const fillBase = sectionFillColor(lowerIsBetter, theme.colors);
  const rba = rbaRate != null ? rbaRate / 100 : null;
  const rbaIn = rba != null && rba >= min && rba <= max;
  const a11ySummary = ribbonA11ySummary(stats, section, rbaRate);

  return (
    <View accessible accessibilityRole="image" accessibilityLabel={a11ySummary}>
      <View
        onLayout={(e) => setW(e.nativeEvent.layout.width)}
        style={{ width: '100%', height: h }}
        importantForAccessibility="no-hide-descendants"
      >
        <Svg width={layoutW} height={h}>
          <Defs>
            <LinearGradient id={fillGradId} x1="0" y1="0" x2="1" y2="0">
              <Stop offset="0" stopColor={fillBase} stopOpacity={0.12} />
              <Stop offset="0.5" stopColor={fillBase} stopOpacity={0.2} />
              <Stop offset="1" stopColor={fillBase} stopOpacity={0.12} />
            </LinearGradient>
          </Defs>
          <AnimatedRect
            animatedProps={barAnimatedProps}
            x={pad}
            y={barY}
            height={barH}
            rx={barH / 2}
            fill={theme.colors.surfaceAlt}
          />
          <AnimatedRect
            animatedProps={barAnimatedProps}
            x={pad}
            y={barY}
            height={barH}
            rx={barH / 2}
            fill={`url(#${fillGradId})`}
          />
          <Rect x={pad} y={barY} width={tickW} height={barH} rx={1} fill={leftColor} />
          <AnimatedRect
            animatedProps={rightTickAnimatedProps}
            y={barY}
            width={tickW}
            height={barH}
            rx={1}
            fill={rightColor}
          />
          {mean !== null ? (
            <AnimatedLine
              animatedProps={meanAnimatedProps}
              x1={x(mean)}
              y1={barY - 3}
              x2={x(mean)}
              y2={barY + barH + 3}
              stroke={theme.colors.text}
              strokeWidth={1.5}
              strokeDasharray={`${meanLineLen}`}
            />
          ) : null}
          {median !== null ? (
            <Circle cx={x(median)} cy={barY + barH / 2} r={barH / 2 + 1} fill={theme.colors.surface} stroke={theme.colors.text} strokeWidth={2} />
          ) : null}
          {rbaIn ? (
            <>
              <AnimatedLine
                animatedProps={rbaAnimatedProps}
                x1={x(rba!)}
                y1={barY - 5}
                x2={x(rba!)}
                y2={barY + barH + 5}
                stroke={theme.colors.primary}
                strokeWidth={2}
                strokeDasharray={`${rbaLineLen}`}
              />
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
