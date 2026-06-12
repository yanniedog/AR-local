import React, { useMemo, useState } from 'react';
import { View } from 'react-native';
import Svg, { G, Rect, Text as SvgText } from 'react-native-svg';

import { SECTIONS } from '../../constants';
import { rateHeatmapModel } from '../../data/vizModels';
import { moveTone } from '../../lib/moveSemantics';
import type { BankHistoryPoint, SectionKey } from '../../types';
import { withAlpha } from '../../theme/colors';
import { useTheme } from '../../theme/ThemeProvider';
import { AppText, Row } from '../ui';

const CELL_GAP = 3;
const LABEL_W = 26;
const LABEL_H = 14;
const DAY_LABELS = ['M', '', 'W', '', 'F', '', 'S'];

/**
 * Market calendar: one square per day, coloured by which way the section's
 * typical (median) rate moved. Tap a day to rewind the market list below.
 */
export function RateHeatCalendar({
  dates,
  points,
  section,
  selectedDate,
  onDateSelect,
}: {
  dates: string[];
  points: BankHistoryPoint[];
  section: SectionKey;
  selectedDate?: string | null;
  onDateSelect?: (date: string) => void;
}) {
  const theme = useTheme();
  const [width, setWidth] = useState(0);
  const model = useMemo(() => rateHeatmapModel(dates, points), [dates, points]);
  if (!model) {
    return (
      <AppText variant="small" color="textMuted">
        The calendar needs at least two days of history — check back after the next refresh.
      </AppText>
    );
  }

  const weeks = model.weeks.length;
  const cell = width > 0 ? Math.max(8, Math.min(20, (width - LABEL_W) / weeks - CELL_GAP)) : 0;
  const gridW = LABEL_W + weeks * (cell + CELL_GAP);
  const gridH = LABEL_H + 7 * (cell + CELL_GAP);
  const goodInk = theme.colors.success;
  const badInk = theme.colors.danger;

  const fillFor = (deltaBps: number | null, hasData: boolean, intensity: number): string => {
    if (!hasData) return withAlpha(theme.colors.textFaint, theme.dark ? 0.1 : 0.08);
    if (deltaBps == null || deltaBps === 0) return theme.colors.skeleton;
    const tone = moveTone(section, deltaBps);
    return withAlpha(tone === 'danger' ? badInk : goodInk, 0.25 + 0.75 * Math.min(1, intensity));
  };

  const better = SECTIONS[section].lowerIsBetter ? 'Rates fell' : 'Rates rose';
  const worse = SECTIONS[section].lowerIsBetter ? 'Rates rose' : 'Rates fell';

  return (
    <View onLayout={(e) => setWidth(e.nativeEvent.layout.width)}>
      {width > 0 ? (
        <Svg width={gridW} height={gridH} accessibilityLabel={`Daily ${SECTIONS[section].title} rate-move calendar`}>
          {model.monthLabels.map((m) => (
            <SvgText
              key={`${m.weekIndex}-${m.label}`}
              x={LABEL_W + m.weekIndex * (cell + CELL_GAP)}
              y={10}
              fontSize={9}
              fill={theme.colors.textFaint}
            >
              {m.label}
            </SvgText>
          ))}
          {DAY_LABELS.map((label, d) =>
            label ? (
              <SvgText
                key={`day-${d}`}
                x={LABEL_W - 8}
                y={LABEL_H + d * (cell + CELL_GAP) + cell * 0.75}
                fontSize={9}
                fill={theme.colors.textFaint}
                textAnchor="middle"
              >
                {label}
              </SvgText>
            ) : null,
          )}
          {model.weeks.map((week, w) => (
            <G key={`w-${w}`}>
              {week.map((c, d) =>
                c ? (
                  <Rect
                    key={c.date}
                    x={LABEL_W + w * (cell + CELL_GAP)}
                    y={LABEL_H + d * (cell + CELL_GAP)}
                    width={cell}
                    height={cell}
                    rx={3}
                    fill={fillFor(c.deltaBps, c.hasData, c.intensity)}
                    stroke={selectedDate === c.date ? theme.colors.primary : 'none'}
                    strokeWidth={selectedDate === c.date ? 2 : 0}
                    onPress={c.hasData && onDateSelect ? () => onDateSelect(c.date) : undefined}
                  />
                ) : null,
              )}
            </G>
          ))}
        </Svg>
      ) : null}
      <Row gap={12} style={{ marginTop: 8, flexWrap: 'wrap' }}>
        <LegendSwatch color={withAlpha(goodInk, 0.8)} label={better} />
        <LegendSwatch color={withAlpha(badInk, 0.8)} label={worse} />
        <LegendSwatch color={theme.colors.skeleton} label="No change" />
      </Row>
      <AppText variant="tiny" color="textFaint" style={{ marginTop: 4 }}>
        Daily move of the median advertised rate · deeper colour = bigger move · tap a day to rewind
      </AppText>
    </View>
  );
}

function LegendSwatch({ color, label }: { color: string; label: string }) {
  return (
    <Row gap={5}>
      <View style={{ width: 10, height: 10, borderRadius: 3, backgroundColor: color }} />
      <AppText variant="tiny" color="textMuted">
        {label}
      </AppText>
    </Row>
  );
}
