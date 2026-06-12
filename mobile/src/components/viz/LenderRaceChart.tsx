import React, { useMemo, useState } from 'react';
import { Pressable, View } from 'react-native';
import Svg, { Circle, Line, Path, Text as SvgText } from 'react-native-svg';

import type { BankInsightsPayload } from '../../data/bankInsights';
import { formatRate } from '../../data/format';
import { lenderRaceModel } from '../../data/vizModels';
import { formatAxisDateLabel } from '../../data/bankHistoryTransform';
import { openBank } from '../../lib/nav';
import type { Brand, HistoryWindow, SectionKey } from '../../types';
import { withAlpha } from '../../theme/colors';
import { useTheme } from '../../theme/ThemeProvider';
import { BankAvatar } from '../BankAvatar';
import { AppText, Row } from '../ui';

const FALLBACK_PALETTE = ['#3b82f6', '#14b8a6', '#d97706', '#a855f7', '#ef4444', '#0ea5e9', '#84cc16', '#ec4899'];

/**
 * Leaderboard race: today's top lenders traced back through their daily
 * best-rate rankings. Crossing lines = lenders overtaking each other.
 */
export function LenderRaceChart({
  payload,
  section,
  lowerIsBetter,
  window,
  brands,
  height = 170,
  topN = 6,
}: {
  payload: BankInsightsPayload | null;
  section: SectionKey;
  lowerIsBetter: boolean;
  window: HistoryWindow;
  brands?: Record<string, Brand>;
  height?: number;
  topN?: number;
}) {
  const theme = useTheme();
  const [width, setWidth] = useState(0);
  const model = useMemo(
    () => lenderRaceModel(payload, section, lowerIsBetter, window, topN),
    [payload, section, lowerIsBetter, window, topN],
  );
  if (!model) {
    return (
      <AppText variant="small" color="textMuted">
        Not enough ranking history in this window yet.
      </AppText>
    );
  }

  const padL = 24;
  const padR = 10;
  const padT = 8;
  const padB = 18;
  const innerW = Math.max(1, width - padL - padR);
  const innerH = height - padT - padB;
  const lanes = model.topN;
  const xAt = (i: number) =>
    padL + (model.dates.length === 1 ? innerW / 2 : (i / (model.dates.length - 1)) * innerW);
  // Ranks beyond the visible lanes park just below the last lane.
  const yAt = (rank: number) =>
    padT + ((Math.min(rank, lanes + 1) - 1) / lanes) * innerH;

  const colorFor = (provider: string, i: number) =>
    brands?.[provider]?.color || FALLBACK_PALETTE[i % FALLBACK_PALETTE.length];

  return (
    <View>
      <View onLayout={(e) => setWidth(e.nativeEvent.layout.width)} style={{ width: '100%', height }}>
        {width > 0 ? (
          <Svg
            width={width}
            height={height}
            accessibilityLabel={`Top ${model.series.length} lender ranking race over time`}
          >
            {Array.from({ length: lanes }, (_, lane) => (
              <React.Fragment key={`lane-${lane}`}>
                <Line
                  x1={padL}
                  y1={yAt(lane + 1)}
                  x2={width - padR}
                  y2={yAt(lane + 1)}
                  stroke={theme.colors.border}
                  strokeWidth={0.6}
                />
                <SvgText
                  x={padL - 6}
                  y={yAt(lane + 1) + 3}
                  fontSize={9}
                  fill={theme.colors.textFaint}
                  textAnchor="end"
                >
                  {`#${lane + 1}`}
                </SvgText>
              </React.Fragment>
            ))}
            {model.series.map((s, si) => {
              const color = colorFor(s.provider, si);
              let d = '';
              let started = false;
              s.ranks.forEach((rank, i) => {
                if (rank == null) return;
                const seg = `${xAt(i)} ${yAt(rank)}`;
                d += started ? ` L ${seg}` : `M ${seg}`;
                started = true;
              });
              const lastRank = s.ranks[s.ranks.length - 1];
              return (
                <React.Fragment key={s.provider}>
                  {d ? (
                    <Path d={d} stroke={withAlpha(color, 0.85)} strokeWidth={2.2} fill="none" strokeLinejoin="round" />
                  ) : null}
                  {lastRank != null ? (
                    <Circle cx={xAt(s.ranks.length - 1)} cy={yAt(lastRank)} r={4} fill={color} />
                  ) : null}
                </React.Fragment>
              );
            })}
            <SvgText x={padL} y={height - 4} fontSize={9} fill={theme.colors.textFaint}>
              {formatAxisDateLabel(model.dates[0])}
            </SvgText>
            <SvgText x={width - padR} y={height - 4} fontSize={9} fill={theme.colors.textFaint} textAnchor="end">
              {formatAxisDateLabel(model.dates[model.dates.length - 1])}
            </SvgText>
          </Svg>
        ) : null}
      </View>

      {model.series.map((s, si) => (
        <Pressable
          key={s.provider}
          onPress={() => openBank(s.provider)}
          accessibilityRole="button"
          accessibilityLabel={`Rank ${si + 1}, ${s.provider}, ${formatRate(s.current)}${
            s.climbed ? `, ${s.climbed > 0 ? 'up' : 'down'} ${Math.abs(s.climbed)} places` : ''
          }`}
        >
          <Row gap={8} style={{ paddingVertical: 5 }}>
            <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: colorFor(s.provider, si) }} />
            <AppText variant="tiny" weight="700" color="textFaint" style={{ width: 22 }}>
              #{si + 1}
            </AppText>
            <BankAvatar provider={s.provider} size={22} />
            <AppText variant="small" weight="600" numberOfLines={1} style={{ flex: 1 }}>
              {s.provider}
            </AppText>
            {s.climbed !== 0 ? (
              <AppText
                variant="tiny"
                weight="700"
                style={{ color: s.climbed > 0 ? theme.colors.success : theme.colors.danger }}
              >
                {s.climbed > 0 ? '▲' : '▼'} {Math.abs(s.climbed)}
              </AppText>
            ) : null}
            <AppText variant="small" weight="800">
              {formatRate(s.current)}
            </AppText>
          </Row>
        </Pressable>
      ))}
      <AppText variant="tiny" color="textFaint" style={{ marginTop: 4 }}>
        Best advertised rate ranking across {model.fieldSize} lenders · tap a lender for their profile
      </AppText>
    </View>
  );
}
