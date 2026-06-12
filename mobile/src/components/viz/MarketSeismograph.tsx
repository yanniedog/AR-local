import React, { useMemo, useState } from 'react';
import { View, type GestureResponderEvent } from 'react-native';
import Svg, { Line, Polygon, Rect, Text as SvgText } from 'react-native-svg';

import { SECTIONS } from '../../constants';
import { formatAxisDateLabel, rbaChangesInWindow, sliceIndexFromPlotX } from '../../data/bankHistoryTransform';
import { marketActivityModel } from '../../data/vizModels';
import type { BankInsightsPayload } from '../../data/bankInsights';
import { moveTone } from '../../lib/moveSemantics';
import type { HistoryWindow, RbaEntry, SectionKey } from '../../types';
import { withAlpha } from '../../theme/colors';
import { useTheme } from '../../theme/ThemeProvider';
import { AppText, Row } from '../ui';

/**
 * Market seismograph: every detected lender rate move as a mirrored daily bar —
 * hikes ride above the axis, cuts below, RBA decisions marked as diamonds.
 * Tap a day to rewind the market list.
 */
export function MarketSeismograph({
  payload,
  section,
  window,
  rba,
  selectedDate,
  onDateSelect,
  height = 150,
}: {
  payload: BankInsightsPayload | null;
  section: SectionKey;
  window: HistoryWindow;
  rba?: RbaEntry[];
  selectedDate?: string | null;
  onDateSelect?: (date: string) => void;
  height?: number;
}) {
  const theme = useTheme();
  const [width, setWidth] = useState(0);
  const model = useMemo(() => marketActivityModel(payload, section, window), [payload, section, window]);
  const rbaMarks = useMemo(
    () => (rba?.length && model ? rbaChangesInWindow(model.days.map((d) => d.date), rba) : []),
    [rba, model],
  );
  if (!model) {
    return (
      <AppText variant="small" color="textMuted">
        Move activity appears here as the daily feed accumulates.
      </AppText>
    );
  }

  const padL = 8;
  const padR = 8;
  const padT = 16;
  const padB = 18;
  const innerW = Math.max(1, width - padL - padR);
  const innerH = height - padT - padB;
  const midY = padT + innerH / 2;
  const n = model.days.length;
  const slotW = innerW / Math.max(1, n);
  const barW = Math.max(2, Math.min(10, slotW * 0.6));
  const xAt = (i: number) => padL + slotW * i + slotW / 2;
  const scale = model.maxBps > 0 ? innerH / 2 / model.maxBps : 0;

  const upTone = moveTone(section, 1);
  const downTone = moveTone(section, -1);
  const upInk = upTone === 'danger' ? theme.colors.danger : theme.colors.success;
  const downInk = downTone === 'danger' ? theme.colors.danger : theme.colors.success;

  const quiet = model.totalMoves === 0;
  const selectedIdx = selectedDate ? model.days.findIndex((d) => d.date === selectedDate) : -1;

  const handleTap = (e: GestureResponderEvent) => {
    if (!onDateSelect || !n) return;
    const idx = sliceIndexFromPlotX(e.nativeEvent.locationX - padL, innerW, n);
    const day = model.days[idx];
    if (day) onDateSelect(day.date);
  };

  return (
    <View>
      <View
        onLayout={(e) => setWidth(e.nativeEvent.layout.width)}
        onTouchEnd={handleTap}
        accessible
        accessibilityRole="image"
        accessibilityLabel={`${SECTIONS[section].title} rate-move seismograph: ${model.totalMoves} lender moves in this window`}
        style={{ width: '100%', height }}
      >
        {width > 0 ? (
          <Svg width={width} height={height}>
            <Line x1={padL} y1={midY} x2={width - padR} y2={midY} stroke={theme.colors.border} strokeWidth={1} />
            {model.days.map((d, i) => {
              const x = xAt(i);
              return (
                <React.Fragment key={d.date}>
                  {selectedIdx === i ? (
                    <Rect
                      x={x - slotW / 2}
                      y={padT}
                      width={slotW}
                      height={innerH}
                      fill={withAlpha(theme.colors.primary, 0.14)}
                    />
                  ) : null}
                  {d.hikeBps > 0 ? (
                    <Rect
                      x={x - barW / 2}
                      y={midY - d.hikeBps * scale}
                      width={barW}
                      height={Math.max(2, d.hikeBps * scale)}
                      rx={1}
                      fill={withAlpha(upInk, 0.85)}
                    />
                  ) : null}
                  {d.cutBps > 0 ? (
                    <Rect
                      x={x - barW / 2}
                      y={midY}
                      width={barW}
                      height={Math.max(2, d.cutBps * scale)}
                      rx={1}
                      fill={withAlpha(downInk, 0.85)}
                    />
                  ) : null}
                </React.Fragment>
              );
            })}
            {rbaMarks.map((mark) => {
              const idx = model.days.findIndex((d) => d.date === mark.snap);
              if (idx < 0) return null;
              const x = xAt(idx);
              return (
                <React.Fragment key={mark.date}>
                  <Polygon
                    points={`${x},${padT - 10} ${x + 5},${padT - 4} ${x},${padT + 2} ${x - 5},${padT - 4}`}
                    fill={theme.colors.rba}
                  />
                  <SvgText x={x + 8} y={padT - 2} fontSize={9} fill={theme.colors.rba} fontWeight="600">
                    RBA {mark.bp > 0 ? `+${mark.bp}` : mark.bp}
                  </SvgText>
                </React.Fragment>
              );
            })}
            <SvgText x={padL} y={height - 4} fontSize={9} fill={theme.colors.textFaint}>
              {formatAxisDateLabel(model.days[0].date)}
            </SvgText>
            <SvgText x={width - padR} y={height - 4} fontSize={9} fill={theme.colors.textFaint} textAnchor="end">
              {formatAxisDateLabel(model.days[n - 1].date)}
            </SvgText>
          </Svg>
        ) : null}
      </View>
      <Row gap={12} style={{ marginTop: 6, flexWrap: 'wrap' }}>
        <AppText variant="tiny" color="textMuted">
          {quiet
            ? 'A quiet market — no lender moves detected in this window.'
            : `${model.totalMoves} lender move${model.totalMoves === 1 ? '' : 's'} · bars above the line are increases, below are cuts`}
        </AppText>
      </Row>
    </View>
  );
}
