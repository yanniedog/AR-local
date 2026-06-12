import React, { useMemo, useState } from 'react';
import { Pressable, View } from 'react-native';
import Svg, { Circle, Line, Text as SvgText } from 'react-native-svg';

import { rbaPassThrough, type BankInsightsPayload, type PassThroughRow } from '../../data/bankInsights';
import { formatRunDate } from '../../data/format';
import { openBank } from '../../lib/nav';
import type { RbaEntry } from '../../types';
import { withAlpha } from '../../theme/colors';
import { useTheme } from '../../theme/ThemeProvider';
import { BankAvatar } from '../BankAvatar';
import { AppText, Badge, Row } from '../ui';

/**
 * RBA response map: every lender plotted by how fast (x, days) and how fully
 * (y, bps) they moved their best mortgage rate after the latest cash-rate
 * decision. The dashed line is the decision itself — on it = full pass-through.
 */
export function RbaResponseScatter({
  payload,
  rba,
  height = 190,
}: {
  payload: BankInsightsPayload | null;
  rba: RbaEntry[];
  height?: number;
}) {
  const theme = useTheme();
  const [width, setWidth] = useState(0);
  const model = useMemo(() => rbaPassThrough(payload, rba), [payload, rba]);
  if (!model) {
    return (
      <AppText variant="small" color="textMuted">
        No RBA decision falls inside the tracked window yet. When the next one lands, every
        lender's speed and pass-through size will be mapped here.
      </AppText>
    );
  }

  const { decision, rows } = model;
  const moved = rows.filter((r) => r.daysToFirstMove != null);
  const holdouts = rows.filter((r) => r.daysToFirstMove == null);
  const isCut = decision.bps < 0;
  const fullPasses = rows.filter((r) =>
    isCut ? r.passedBps <= decision.bps : r.passedBps >= decision.bps,
  );

  const padL = 40;
  const padR = 12;
  const padT = 10;
  const padB = 26;
  const innerW = Math.max(1, width - padL - padR);
  const innerH = height - padT - padB;

  const maxDays = Math.max(7, ...moved.map((r) => r.daysToFirstMove ?? 0));
  const bpsValues = rows.map((r) => r.passedBps).concat([decision.bps, 0]);
  const yMin = Math.min(...bpsValues) - 5;
  const yMax = Math.max(...bpsValues) + 5;
  const ySpan = yMax - yMin || 1;
  const xAt = (days: number) => padL + (days / maxDays) * innerW;
  const yAt = (bps: number) => padT + innerH - ((bps - yMin) / ySpan) * innerH;

  const dotColor = (r: PassThroughRow): string => {
    const full = isCut ? r.passedBps <= decision.bps : r.passedBps >= decision.bps;
    if (full) return theme.colors.success;
    if (r.passedBps === 0) return theme.colors.textFaint;
    return theme.colors.warning;
  };

  const fastest = moved.length
    ? moved.reduce((acc, r) => ((r.daysToFirstMove ?? 99) < (acc.daysToFirstMove ?? 99) ? r : acc))
    : null;

  return (
    <View>
      <AppText variant="small" color="textMuted" style={{ marginBottom: 6 }}>
        RBA {isCut ? 'cut' : 'raised'} by {Math.abs(decision.bps)} bps on {formatRunDate(decision.date)}.
        Each dot is a lender: further left = faster reaction, on the dashed line = full pass-through.
      </AppText>
      <Row gap={6} style={{ flexWrap: 'wrap', marginBottom: 8 }}>
        <Badge label={`${fullPasses.length} full pass${fullPasses.length === 1 ? '' : 'es'}`} tone="success" />
        <Badge label={`${moved.length} moved`} tone="primary" />
        {holdouts.length ? <Badge label={`${holdouts.length} yet to move`} tone="warning" /> : null}
      </Row>
      <View
        onLayout={(e) => setWidth(e.nativeEvent.layout.width)}
        accessible
        accessibilityRole="image"
        accessibilityLabel={`RBA response map: ${moved.length} lenders moved, ${fullPasses.length} passed the full ${Math.abs(decision.bps)} basis points, ${holdouts.length} yet to move`}
        style={{ width: '100%', height }}
      >
        {width > 0 ? (
          <Svg width={width} height={height}>
            <Line x1={padL} y1={yAt(0)} x2={width - padR} y2={yAt(0)} stroke={theme.colors.border} strokeWidth={1} />
            <Line
              x1={padL}
              y1={yAt(decision.bps)}
              x2={width - padR}
              y2={yAt(decision.bps)}
              stroke={theme.colors.rba}
              strokeWidth={1.4}
              strokeDasharray="5 4"
            />
            <SvgText x={padL + 2} y={yAt(decision.bps) - 4} fontSize={9} fill={theme.colors.rba} fontWeight="600">
              full pass ({decision.bps > 0 ? '+' : ''}
              {decision.bps} bps)
            </SvgText>
            <SvgText x={padL - 6} y={yAt(0) + 3} fontSize={9} fill={theme.colors.textFaint} textAnchor="end">
              0
            </SvgText>
            {[7, 14, 21, 28].filter((d) => d <= maxDays).map((d) => (
              <React.Fragment key={d}>
                <Line
                  x1={xAt(d)}
                  y1={padT}
                  x2={xAt(d)}
                  y2={padT + innerH}
                  stroke={withAlpha(theme.colors.textFaint, 0.18)}
                  strokeWidth={0.8}
                />
                <SvgText x={xAt(d)} y={height - 12} fontSize={9} fill={theme.colors.textFaint} textAnchor="middle">
                  {d}d
                </SvgText>
              </React.Fragment>
            ))}
            {moved.map((r) => (
              <Circle
                key={r.provider}
                cx={xAt(r.daysToFirstMove!)}
                cy={yAt(r.passedBps)}
                r={5}
                fill={withAlpha(dotColor(r), 0.85)}
              />
            ))}
            <SvgText x={padL + innerW / 2} y={height - 1} fontSize={9} fill={theme.colors.textFaint} textAnchor="middle">
              days from decision to first move
            </SvgText>
          </Svg>
        ) : null}
      </View>
      {fastest ? (
        <Pressable
          onPress={() => openBank(fastest.provider)}
          accessibilityRole="button"
          accessibilityLabel={`Fastest responder ${fastest.provider}, moved after ${fastest.daysToFirstMove} days`}
        >
          <Row gap={8} style={{ marginTop: 8 }}>
            <BankAvatar provider={fastest.provider} size={22} />
            <AppText variant="tiny" color="textMuted" style={{ flex: 1 }} numberOfLines={1}>
              Fastest responder: <AppText variant="tiny" weight="700">{fastest.provider}</AppText> after{' '}
              {fastest.daysToFirstMove} day{fastest.daysToFirstMove === 1 ? '' : 's'} (
              {fastest.passedBps > 0 ? '+' : ''}
              {fastest.passedBps} bps)
            </AppText>
          </Row>
        </Pressable>
      ) : null}
    </View>
  );
}
