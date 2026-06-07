import React, { useState } from 'react';
import { View } from 'react-native';
import Svg, { Circle, Line, Path, Text as SvgText } from 'react-native-svg';

import type { RbaEntry } from '../types';
import { useTheme } from '../theme/ThemeProvider';
import { AppText } from './ui';

/** A compact step-line chart of the RBA cash-rate target over time. */
export function RbaChart({ data, height = 160 }: { data: RbaEntry[]; height?: number }) {
  const theme = useTheme();
  const [width, setWidth] = useState(0);

  if (!data.length) return null;
  const padL = 8;
  const padR = 40;
  const padT = 16;
  const padB = 18;

  const rates = data.map((d) => d.rate);
  const minR = Math.min(...rates);
  const maxR = Math.max(...rates);
  const span = maxR - minR || 1;

  const innerW = Math.max(1, width - padL - padR);
  const innerH = height - padT - padB;

  const x = (i: number) => padL + (data.length === 1 ? innerW / 2 : (i / (data.length - 1)) * innerW);
  const y = (rate: number) => padT + innerH - ((rate - minR) / span) * innerH;

  // Step-after path.
  let d = `M ${x(0)} ${y(data[0].rate)}`;
  for (let i = 1; i < data.length; i++) {
    d += ` L ${x(i)} ${y(data[i - 1].rate)} L ${x(i)} ${y(data[i].rate)}`;
  }

  const last = data[data.length - 1];

  return (
    <View onLayout={(e) => setWidth(e.nativeEvent.layout.width)} style={{ width: '100%', height }}>
      {width > 0 ? (
        <Svg width={width} height={height}>
          <Line x1={padL} y1={y(maxR)} x2={width - padR} y2={y(maxR)} stroke={theme.colors.border} strokeWidth={1} />
          <Line x1={padL} y1={y(minR)} x2={width - padR} y2={y(minR)} stroke={theme.colors.border} strokeWidth={1} />
          <SvgText x={width - padR + 4} y={y(maxR) + 4} fontSize={10} fill={theme.colors.textFaint}>
            {maxR.toFixed(2)}
          </SvgText>
          <SvgText x={width - padR + 4} y={y(minR) + 4} fontSize={10} fill={theme.colors.textFaint}>
            {minR.toFixed(2)}
          </SvgText>
          <Path d={d} stroke={theme.colors.primary} strokeWidth={2.5} fill="none" />
          <Circle cx={x(data.length - 1)} cy={y(last.rate)} r={4} fill={theme.colors.primary} />
          <SvgText
            x={x(data.length - 1)}
            y={y(last.rate) - 8}
            fontSize={11}
            fontWeight="bold"
            fill={theme.colors.text}
            textAnchor="end"
          >
            {last.rate.toFixed(2)}%
          </SvgText>
        </Svg>
      ) : null}
      <AppText variant="tiny" color="textFaint" style={{ marginTop: 2 }}>
        {data[0].date} → {last.date}
      </AppText>
    </View>
  );
}
