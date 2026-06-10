import React, { useEffect, useMemo, useRef, useState } from 'react';
import { View } from 'react-native';
import Animated, {
  Easing,
  useAnimatedProps,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';
import Svg, { Circle, Line, Path, Text as SvgText } from 'react-native-svg';

import { formatRate, formatRateDigits } from '../data/format';
import { rbaChartA11ySummary } from '../lib/a11ySummaries';
import type { RbaEntry } from '../types';
import { useTheme } from '../theme/ThemeProvider';
import { AppText } from './ui';

const AnimatedPath = Animated.createAnimatedComponent(Path);

const DRAW_MS = 800;

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

function estimateStepPathLength(data: RbaEntry[], x: (i: number) => number, y: (rate: number) => number): number {
  if (data.length <= 1) return 1;
  let len = 0;
  for (let i = 1; i < data.length; i += 1) {
    len += Math.abs(x(i) - x(i - 1));
    len += Math.abs(y(data[i].rate) - y(data[i - 1].rate));
  }
  return Math.max(1, len);
}

/** A compact step-line chart of the RBA cash-rate target over time. */
export function RbaChart({ data, height = 160 }: { data: RbaEntry[]; height?: number }) {
  const theme = useTheme();
  const [width, setWidth] = useState(0);
  const drawProgress = useFirstMountDrawIn();

  const padL = 8;
  const padR = 40;
  const padT = 16;
  const padB = 18;

  const rates = data.map((d) => d.rate);
  const minR = data.length ? Math.min(...rates) : 0;
  const maxR = data.length ? Math.max(...rates) : 1;
  const span = maxR - minR || 1;

  const innerW = Math.max(1, width - padL - padR);
  const innerH = height - padT - padB;

  const x = (i: number) => padL + (data.length === 1 ? innerW / 2 : (i / (data.length - 1)) * innerW);
  const y = (rate: number) => padT + innerH - ((rate - minR) / span) * innerH;

  const pathD = useMemo(() => {
    if (!data.length) return '';
    let d = `M ${x(0)} ${y(data[0].rate)}`;
    for (let i = 1; i < data.length; i += 1) {
      d += ` L ${x(i)} ${y(data[i - 1].rate)} L ${x(i)} ${y(data[i].rate)}`;
    }
    return d;
  }, [data, innerW, innerH, minR, maxR]);

  const pathLength = useMemo(() => {
    if (!data.length || width <= 0) return 1;
    return estimateStepPathLength(data, x, y);
  }, [data, width, innerW, innerH, minR, maxR]);

  const pathAnimatedProps = useAnimatedProps(() => ({
    strokeDashoffset: pathLength * (1 - drawProgress.value),
  }));

  if (!data.length) return null;

  const last = data[data.length - 1];
  const a11ySummary = rbaChartA11ySummary(data);

  return (
    <View
      accessible
      accessibilityRole="image"
      accessibilityLabel={a11ySummary}
      onLayout={(e) => setWidth(e.nativeEvent.layout.width)}
      style={{ width: '100%', height }}
    >
      {width > 0 ? (
        <Svg width={width} height={height} importantForAccessibility="no-hide-descendants">
          <Line x1={padL} y1={y(maxR)} x2={width - padR} y2={y(maxR)} stroke={theme.colors.border} strokeWidth={1} />
          <Line x1={padL} y1={y(minR)} x2={width - padR} y2={y(minR)} stroke={theme.colors.border} strokeWidth={1} />
          <SvgText x={width - padR + 4} y={y(maxR) + 4} fontSize={10} fill={theme.colors.textFaint}>
            {formatRateDigits(maxR)}
          </SvgText>
          <SvgText x={width - padR + 4} y={y(minR) + 4} fontSize={10} fill={theme.colors.textFaint}>
            {formatRateDigits(minR)}
          </SvgText>
          <AnimatedPath
            animatedProps={pathAnimatedProps}
            d={pathD}
            stroke={theme.colors.primary}
            strokeWidth={2.5}
            fill="none"
            strokeDasharray={pathLength}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <Circle cx={x(data.length - 1)} cy={y(last.rate)} r={4} fill={theme.colors.primary} />
          <SvgText
            x={x(data.length - 1)}
            y={y(last.rate) - 8}
            fontSize={11}
            fontWeight="bold"
            fill={theme.colors.text}
            textAnchor="end"
          >
            {formatRate(last.rate)}
          </SvgText>
        </Svg>
      ) : null}
      <AppText variant="tiny" color="textFaint" style={{ marginTop: 2 }}>
        {data[0].date} → {last.date}
      </AppText>
    </View>
  );
}
