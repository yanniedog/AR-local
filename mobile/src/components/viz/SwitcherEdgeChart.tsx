import React, { useMemo, useState } from 'react';
import { View } from 'react-native';
import Svg, { Circle, Line, Path, Text as SvgText } from 'react-native-svg';

import { formatAxisDateLabel } from '../../data/bankHistoryTransform';
import { spreadGapModel } from '../../data/vizModels';
import type { BankHistoryPoint, SectionKey } from '../../types';
import { SECTIONS } from '../../constants';
import { withAlpha } from '../../theme/colors';
import { useTheme } from '../../theme/ThemeProvider';
import { AppText, Badge, Row } from '../ui';

/**
 * Switcher's edge: how far the best advertised rate sits from the market's
 * typical (median) rate — the daily payoff of shopping around.
 */
export function SwitcherEdgeChart({
  dates,
  points,
  section,
  height = 150,
}: {
  dates: string[];
  points: BankHistoryPoint[];
  section: SectionKey;
  height?: number;
}) {
  const theme = useTheme();
  const [width, setWidth] = useState(0);
  const lowerIsBetter = SECTIONS[section].lowerIsBetter;
  const model = useMemo(
    () => spreadGapModel(dates, points, lowerIsBetter),
    [dates, points, lowerIsBetter],
  );
  if (!model) {
    return (
      <AppText variant="small" color="textMuted">
        No spread history available for this window yet.
      </AppText>
    );
  }

  const padL = 34;
  const padR = 10;
  const padT = 8;
  const padB = 18;
  const innerW = Math.max(1, width - padL - padR);
  const innerH = height - padT - padB;
  const yMax = Math.max(1, model.maxBps * 1.1);
  const n = model.points.length;
  const xAt = (i: number) => padL + (n === 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  const yAt = (bps: number) => padT + innerH - (bps / yMax) * innerH;

  let line = '';
  let area = '';
  let started = false;
  let lastX: number | null = null;
  let firstX: number | null = null;
  model.points.forEach((p, i) => {
    if (p.gapBps == null) return;
    const x = xAt(i);
    const y = yAt(p.gapBps);
    line += started ? ` L ${x} ${y}` : `M ${x} ${y}`;
    if (!started) firstX = x;
    lastX = x;
    started = true;
  });
  if (started && firstX != null && lastX != null) {
    area = `${line} L ${lastX} ${yAt(0)} L ${firstX} ${yAt(0)} Z`;
  }

  const ink = theme.colors.primary;
  const widestIdx = model.widestDate ? model.points.findIndex((p) => p.date === model.widestDate) : -1;
  const widestPoint = widestIdx >= 0 ? model.points[widestIdx] : null;
  const atWidest =
    model.currentBps != null && model.maxBps > 0 && model.currentBps >= model.maxBps;

  return (
    <View>
      <Row gap={8} style={{ alignItems: 'flex-end', marginBottom: 6 }}>
        <AppText variant="rateHero" style={{ color: ink }}>
          {model.currentBps != null ? `${Math.round(model.currentBps)} bps` : '—'}
        </AppText>
        <View style={{ flex: 1, paddingBottom: 4 }}>
          <AppText variant="tiny" color="textMuted">
            today's gap between the typical rate and the best on the market
          </AppText>
        </View>
        {atWidest ? <Badge label="widest in window" tone="primary" /> : null}
      </Row>
      <View onLayout={(e) => setWidth(e.nativeEvent.layout.width)} style={{ width: '100%', height }}>
        {width > 0 && started ? (
          <Svg
            width={width}
            height={height}
            accessibilityLabel={`Gap between typical and best ${SECTIONS[section].title} rate over time`}
          >
            {[0, 0.5, 1].map((frac) => {
              const bps = yMax * frac;
              const y = yAt(bps);
              return (
                <React.Fragment key={frac}>
                  <Line x1={padL} y1={y} x2={width - padR} y2={y} stroke={theme.colors.border} strokeWidth={0.6} />
                  <SvgText x={padL - 4} y={y + 3} fontSize={9} fill={theme.colors.textFaint} textAnchor="end">
                    {Math.round(bps)}
                  </SvgText>
                </React.Fragment>
              );
            })}
            <Path d={area} fill={withAlpha(ink, theme.dark ? 0.28 : 0.18)} />
            <Path d={line} stroke={ink} strokeWidth={2} fill="none" strokeLinecap="round" />
            {widestPoint?.gapBps != null && !atWidest ? (
              <Circle cx={xAt(widestIdx)} cy={yAt(widestPoint.gapBps)} r={3.5} fill={theme.colors.warning} />
            ) : null}
            <SvgText x={padL} y={height - 4} fontSize={9} fill={theme.colors.textFaint}>
              {formatAxisDateLabel(model.points[0].date)}
            </SvgText>
            <SvgText x={width - padR} y={height - 4} fontSize={9} fill={theme.colors.textFaint} textAnchor="end">
              {formatAxisDateLabel(model.points[n - 1].date)}
            </SvgText>
          </Svg>
        ) : null}
      </View>
      <AppText variant="tiny" color="textFaint" style={{ marginTop: 4 }}>
        A widening gap means switching {lowerIsBetter ? 'saves' : 'earns'} more than sticking with a typical{' '}
        {SECTIONS[section].short.toLowerCase()} rate
      </AppText>
    </View>
  );
}
