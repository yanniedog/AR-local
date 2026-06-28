import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Platform, View, type GestureResponderEvent, type PointerEvent } from 'react-native';
import Animated, {
  Easing,
  useAnimatedProps,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';
import Svg, { G, Line, Path, Polygon, Rect, Text as SvgText } from 'react-native-svg';

import type { BankHistoryPoint, HistoryWindow, RbaEntry, SectionKey } from '../types';
import {
  axisLabelInterval,
  chartYDomain,
  formatAxisDateLabel,
  rbaChangesInWindow,
  rbaHoldsInWindow,
  rbaStepForDates,
  sliceChartTimeline,
  sliceIndexFromPlotX,
} from '../data/bankHistoryTransform';
import { SECTIONS } from '../constants';
import { bankHistoryChartA11ySummary } from '../lib/a11ySummaries';
import { buildBandPath, buildLinePath } from '../lib/chartSvgPaths';
import { debugLog } from '../lib/debugLog';
import { withAlpha } from '../theme/colors';
import { useTheme } from '../theme/ThemeProvider';
import { AppText, Chip, Row } from './ui';

const WINDOW_OPTIONS: { value: HistoryWindow; label: string }[] = [
  { value: '30D', label: '30D' },
  { value: '90D', label: '90D' },
  { value: '1Y', label: '1Y' },
  { value: 'All', label: 'All' },
];

const DRAW_MS = 850;
const TOUCH_DECIDE_PX = 8;

const AnimatedPath = Animated.createAnimatedComponent(Path);

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

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function finiteCoord(value: number): number | null {
  return Number.isFinite(value) ? value : null;
}

export interface HighlightSeries {
  /** Value per timeline date (YMD). Missing/nullish dates render as gaps in the line. */
  values: Record<string, number | null>;
  label: string;
  color?: string;
}

export interface BankHistoryChartProps {
  dates: string[];
  points: BankHistoryPoint[];
  rba?: RbaEntry[];
  /** RBA meeting dates the rate was held (rendered as hollow diamonds on the step line). */
  rbaHolds?: string[];
  section: SectionKey;
  onDateSelect?: (date: string) => void;
  height?: number;
  /** Full retained timeline before window slice (defaults to `dates`). */
  allDates?: string[];
  /** Optional emphasized line (e.g. one product's rate) drawn over the section context. */
  highlightSeries?: HighlightSeries | null;
}

function stepPath(
  values: (number | null)[],
  xAt: (i: number) => number,
  yAt: (v: number) => number,
): string | null {
  let d = '';
  let started = false;
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    if (!isFiniteNumber(v)) continue;
    const x = finiteCoord(xAt(i));
    const y = finiteCoord(yAt(v));
    if (x == null || y == null) continue;
    if (!started) {
      d = `M ${x} ${y}`;
      started = true;
      continue;
    }
    const prev = values[i - 1];
    const prevY =
      isFiniteNumber(prev) ? finiteCoord(yAt(prev)) : y;
    if (prevY == null) continue;
    d += ` L ${x} ${prevY} L ${x} ${y}`;
  }
  return d || null;
}

/** Time-slice ribbon chart: min/max band, mean + median lines, optional RBA + highlight series. */
export function BankHistoryChart({
  dates,
  points,
  rba,
  rbaHolds,
  section,
  onDateSelect,
  height = 180,
  allDates,
  highlightSeries,
}: BankHistoryChartProps) {
  const theme = useTheme();
  const [width, setWidth] = useState(0);
  const [window, setWindow] = useState<HistoryWindow>('30D');
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [hoverDate, setHoverDate] = useState<string | null>(null);
  const touchModeRef = useRef<'h' | 'v' | null>(null);
  const touchStartRef = useRef({ x: 0, y: 0 });
  const drawProgress = useFirstMountDrawIn();
  const strokeLength = useMemo(() => Math.max(1, Math.max(1, width - 52) * 1.2), [width]);
  const lineDrawProps = useAnimatedProps(() => ({
    strokeDashoffset: strokeLength * (1 - drawProgress.value),
  }));
  const bandDrawProps = useAnimatedProps(() => ({
    opacity: drawProgress.value,
  }));

  const timeline = allDates ?? dates;
  const sliced = useMemo(() => {
    if (!Array.isArray(dates) || !Array.isArray(points) || !Array.isArray(timeline) || !dates.length || !points.length) {
      debugLog.warn('BankHistoryChart', 'invalid chart inputs');
      return { dates: [] as string[], points: [] as BankHistoryPoint[] };
    }
    try {
      return sliceChartTimeline(timeline, points, window);
    } catch (err) {
      debugLog.warn('BankHistoryChart', `sliceChartTimeline failed: ${String((err as Error)?.message ?? err)}`);
      return { dates: [] as string[], points: [] as BankHistoryPoint[] };
    }
  }, [timeline, dates, points, window]);

  const plotDates = sliced.dates;
  const plotPoints = sliced.points;
  const showRba = section === 'Mortgage' && !!rba?.length;

  const rbaSteps = useMemo(
    () => (showRba && rba ? rbaStepForDates(plotDates, rba) : []),
    [showRba, rba, plotDates],
  );
  const rbaMarks = useMemo(
    () => (showRba && rba ? rbaChangesInWindow(plotDates, rba) : []),
    [showRba, rba, plotDates],
  );
  const rbaHoldMarks = useMemo(
    () => (showRba && rba ? rbaHoldsInWindow(plotDates, rbaHolds, rba) : []),
    [showRba, rba, rbaHolds, plotDates],
  );

  const highlightValues = useMemo(
    () => (highlightSeries ? plotDates.map((d) => highlightSeries.values[d] ?? null) : null),
    [highlightSeries, plotDates],
  );

  const yDomain = useMemo(
    () => chartYDomain(plotPoints, rbaSteps, highlightValues ?? []),
    [plotPoints, rbaSteps, highlightValues],
  );

  if (!plotDates.length || !plotPoints.length) return null;

  const hasPlottableValues = plotPoints.some(
    (p) => isFiniteNumber(p.min) || isFiniteNumber(p.max) || isFiniteNumber(p.mean),
  );
  if (!hasPlottableValues) {
    debugLog.warn('BankHistoryChart', 'no finite plot values');
    return null;
  }

  const padL = 44;
  const padR = 8;
  const padT = rbaMarks.length ? 28 : 14;
  const padB = 22;
  const innerW = Math.max(1, width - padL - padR);
  const innerH = height - padT - padB;
  const span = yDomain.max - yDomain.min || 0.001;

  const xAt = (i: number) =>
    padL + (plotDates.length === 1 ? innerW / 2 : (i / (plotDates.length - 1)) * innerW);
  const yAt = (v: number) => padT + innerH - ((v - yDomain.min) / span) * innerH;
  const pct = (v: number) => `${(v * 100).toFixed(2)}%`;

  const mins = plotPoints.map((p) => p.min);
  const maxs = plotPoints.map((p) => p.max);
  const means = plotPoints.map((p) => p.mean);
  const medians = plotPoints.map((p) => p.median);
  const band = buildBandPath(plotDates, mins, maxs, xAt, yAt);
  const meanLine = buildLinePath(means, xAt, yAt);
  const medianLine = buildLinePath(medians, xAt, yAt);
  const minLine = buildLinePath(mins, xAt, yAt);
  const maxLine = buildLinePath(maxs, xAt, yAt);
  const rbaLine = showRba ? stepPath(rbaSteps, xAt, yAt) : null;
  const highlightLine = highlightValues ? buildLinePath(highlightValues, xAt, yAt, true) : null;

  const rateInk = SECTIONS[section].lowerIsBetter ? theme.colors.rateLoan : theme.colors.rateDeposit;
  const ribbonColor = rateInk;
  const bandFill = withAlpha(rateInk, theme.dark ? 0.35 : 0.28);
  const rbaInk = theme.colors.rba;
  const rbaBand = withAlpha(rbaInk, 0.42);
  const crosshairColor = withAlpha(theme.colors.primary, theme.dark ? 0.6 : 0.55);
  const highlightColor = highlightSeries?.color ?? theme.colors.text;

  const labelEvery = axisLabelInterval(plotDates.length);
  const pinnedDate =
    selectedDate && plotDates.includes(selectedDate) ? selectedDate : plotDates.at(-1) ?? '';
  const activeDate =
    hoverDate && plotDates.includes(hoverDate) ? hoverDate : pinnedDate;
  const activeIndex = Math.max(0, plotDates.indexOf(activeDate));
  const activePoint = plotPoints.find((p) => p.date === activeDate);
  const activeHighlight =
    highlightValues && isFiniteNumber(highlightValues[activeIndex])
      ? highlightValues[activeIndex]
      : null;

  const handleSlicePress = (date: string) => {
    setSelectedDate(date);
    onDateSelect?.(date);
  };

  const setHoverFromPlotX = (plotLocalX: number) => {
    const idx = sliceIndexFromPlotX(plotLocalX, innerW, plotDates.length);
    const date = plotDates[idx];
    if (date) setHoverDate(date);
  };

  const onTouchStartScrub = (e: GestureResponderEvent) => {
    if (e.nativeEvent.touches.length !== 1) {
      touchModeRef.current = 'v';
      return;
    }
    touchModeRef.current = null;
    const t = e.nativeEvent.touches[0];
    touchStartRef.current = { x: t.locationX, y: t.locationY };
  };

  const onTouchMoveScrub = (e: GestureResponderEvent) => {
    if (e.nativeEvent.touches.length !== 1) return;
    const t = e.nativeEvent.touches[0];
    if (touchModeRef.current === null) {
      const dx = Math.abs(t.locationX - touchStartRef.current.x);
      const dy = Math.abs(t.locationY - touchStartRef.current.y);
      if (dx < TOUCH_DECIDE_PX && dy < TOUCH_DECIDE_PX) return;
      touchModeRef.current = dx > dy ? 'h' : 'v';
    }
    if (touchModeRef.current !== 'h') return;
    setHoverFromPlotX(t.locationX);
  };

  const onTouchEndScrub = (e: GestureResponderEvent) => {
    const t = e.nativeEvent.changedTouches[0];
    const mode = touchModeRef.current;
    // Tap pins a slice; releasing a horizontal scrub pins where it ended,
    // so scrubbing also rewinds anything driven by onDateSelect.
    if (t && (mode === null || mode === 'h')) {
      const idx = sliceIndexFromPlotX(t.locationX, innerW, plotDates.length);
      const date = plotDates[idx];
      if (date) handleSlicePress(date);
    }
    touchModeRef.current = null;
    setHoverDate(null);
  };

  // The parent ScrollView steals the gesture on vertical drags and fires
  // touchCancel instead of touchEnd — reset without pinning a date, so the
  // crosshair doesn't stay frozen at the aborted hover position.
  const onTouchCancelScrub = () => {
    touchModeRef.current = null;
    setHoverDate(null);
  };

  const onPointerMoveScrub = (e: PointerEvent) => {
    setHoverFromPlotX(e.nativeEvent.offsetX);
  };

  const onPointerDownScrub = (e: PointerEvent) => {
    const idx = sliceIndexFromPlotX(e.nativeEvent.offsetX, innerW, plotDates.length);
    const date = plotDates[idx];
    if (date) handleSlicePress(date);
  };

  const onAccessibilityScrub = (e: { nativeEvent: { actionName: string } }) => {
    if (e.nativeEvent.actionName === 'increment') {
      const nextIdx = Math.min(plotDates.length - 1, activeIndex + 1);
      const date = plotDates[nextIdx];
      if (date) handleSlicePress(date);
    } else if (e.nativeEvent.actionName === 'decrement') {
      const prevIdx = Math.max(0, activeIndex - 1);
      const date = plotDates[prevIdx];
      if (date) handleSlicePress(date);
    }
  };

  const chartSummary = bankHistoryChartA11ySummary({
    section,
    window,
    activeDate,
    activePoint,
    showRba,
    highlight:
      highlightSeries && activeHighlight != null
        ? { label: highlightSeries.label, value: activeHighlight }
        : undefined,
  });

  return (
    <View>
      <Row gap={6} style={{ marginBottom: 8, flexWrap: 'wrap' }}>
        {WINDOW_OPTIONS.map((opt) => (
          <Chip
            key={opt.value}
            label={opt.label}
            selected={window === opt.value}
            onPress={() => setWindow(opt.value)}
          />
        ))}
      </Row>

      <View
        accessible
        accessibilityRole="image"
        accessibilityLabel={chartSummary}
        onLayout={(e) => setWidth(e.nativeEvent.layout.width)}
        style={{ width: '100%', height }}
      >
        {width > 0 ? (
          <Svg width={width} height={height} importantForAccessibility="no-hide-descendants">
            {[0, 0.5, 1].map((frac) => {
              const v = yDomain.min + span * frac;
              const y = yAt(v);
              return (
                <React.Fragment key={frac}>
                  <Line
                    x1={padL}
                    y1={y}
                    x2={width - padR}
                    y2={y}
                    stroke={theme.colors.border}
                    strokeWidth={1}
                  />
                  <SvgText x={padL - 4} y={y + 4} fontSize={10} fill={theme.colors.textFaint} textAnchor="end">
                    {pct(v)}
                  </SvgText>
                </React.Fragment>
              );
            })}

            {rbaMarks.map((mark) => {
              const idx = plotDates.indexOf(mark.snap);
              if (idx < 0) return null;
              const x = xAt(idx);
              const sliceW = plotDates.length > 1 ? innerW / (plotDates.length - 1) : innerW;
              const half = Math.max(4, sliceW * 0.45);
              return (
                <React.Fragment key={`${mark.date}-${mark.snap}`}>
                  <Rect
                    x={Math.max(padL, x - half)}
                    y={padT}
                    width={Math.min(width - padR, x + half) - Math.max(padL, x - half)}
                    height={innerH}
                    fill={rbaBand}
                  />
                  <SvgText
                    x={Math.max(padL + 2, x - half + 2)}
                    y={padT + 10}
                    fontSize={9}
                    fill={rbaInk}
                    fontWeight="600"
                  >
                    {mark.bp > 0 ? `+${mark.bp}` : mark.bp} bps
                  </SvgText>
                </React.Fragment>
              );
            })}

            {band ? (
              <AnimatedPath animatedProps={bandDrawProps} d={band} fill={bandFill} stroke="none" />
            ) : null}
            {minLine ? (
              <AnimatedPath
                animatedProps={lineDrawProps}
                d={minLine}
                stroke={ribbonColor}
                strokeWidth={0.8}
                fill="none"
                opacity={0.45}
                strokeDasharray={strokeLength}
              />
            ) : null}
            {maxLine ? (
              <AnimatedPath
                animatedProps={lineDrawProps}
                d={maxLine}
                stroke={ribbonColor}
                strokeWidth={0.8}
                fill="none"
                opacity={0.45}
                strokeDasharray={strokeLength}
              />
            ) : null}
            {meanLine ? (
              <AnimatedPath
                animatedProps={lineDrawProps}
                d={meanLine}
                stroke={ribbonColor}
                strokeWidth={2}
                fill="none"
                strokeLinecap="round"
                strokeDasharray={strokeLength}
              />
            ) : null}
            {medianLine ? (
              <AnimatedPath
                animatedProps={bandDrawProps}
                d={medianLine}
                stroke={ribbonColor}
                strokeWidth={1.6}
                fill="none"
                strokeLinecap="round"
                strokeDasharray="5 4"
              />
            ) : null}
            {rbaLine ? (
              <AnimatedPath
                animatedProps={lineDrawProps}
                d={rbaLine}
                stroke={rbaInk}
                strokeWidth={2}
                fill="none"
                strokeDasharray={strokeLength}
                opacity={0.85}
              />
            ) : null}
            {rbaHoldMarks.map((mark) => {
              const idx = plotDates.indexOf(mark.snap);
              if (idx < 0) return null;
              const x = xAt(idx);
              const y = yAt(mark.rate);
              const h = 4.5;
              return (
                <React.Fragment key={`hold-${mark.date}-${mark.snap}`}>
                  <Polygon
                    points={`${x},${y - h} ${x + h},${y} ${x},${y + h} ${x - h},${y}`}
                    fill={theme.colors.surface}
                    stroke={rbaInk}
                    strokeWidth={1.4}
                  />
                  <SvgText
                    x={x}
                    y={y - h - 3}
                    fontSize={8}
                    fill={rbaInk}
                    fontWeight="600"
                    textAnchor="middle"
                  >
                    held
                  </SvgText>
                </React.Fragment>
              );
            })}
            {highlightLine ? (
              <AnimatedPath
                animatedProps={lineDrawProps}
                d={highlightLine}
                stroke={highlightColor}
                strokeWidth={2.6}
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeDasharray={strokeLength}
              />
            ) : null}

            {plotDates.map((date, i) => {
              const isLast = i === plotDates.length - 1;
              const isScheduled = labelEvery === 0 || i % (labelEvery + 1) === 0;
              const isTooCloseToLast = !isLast && (plotDates.length - 1 - i) < (labelEvery + 1) * 0.7;
              if (isLast || (isScheduled && !isTooCloseToLast)) {
                return (
                  <SvgText
                    key={date}
                    x={xAt(i)}
                    y={height - 4}
                    fontSize={10}
                    fill={theme.colors.textFaint}
                    textAnchor="middle"
                  >
                    {formatAxisDateLabel(date)}
                  </SvgText>
                );
              }
              return null;
            })}

            {plotDates.length > 1 ? (
              <Line
                x1={xAt(activeIndex)}
                y1={padT}
                x2={xAt(activeIndex)}
                y2={padT + innerH}
                stroke={crosshairColor}
                strokeWidth={1.4}
                strokeDasharray="4 3"
              />
            ) : null}

            {activePoint?.mean != null && isFiniteNumber(activePoint.mean) ? (
              <CrossMarker cx={xAt(activeIndex)} cy={yAt(activePoint.mean)} color={ribbonColor} />
            ) : null}
            {activeHighlight != null ? (
              <CrossMarker cx={xAt(activeIndex)} cy={yAt(activeHighlight)} color={highlightColor} />
            ) : null}
          </Svg>
        ) : null}

        {plotDates.length > 1 ? (
          <View
            onTouchStart={onTouchStartScrub}
            onTouchMove={onTouchMoveScrub}
            onTouchEnd={onTouchEndScrub}
            onTouchCancel={onTouchCancelScrub}
            {...(Platform.OS === 'web'
              ? {
                  onPointerMove: onPointerMoveScrub,
                  onPointerLeave: () => setHoverDate(null),
                  onPointerDown: onPointerDownScrub,
                }
              : {})}
            accessible
            accessibilityRole="adjustable"
            accessibilityLabel="Scrub history ribbon by date"
            accessibilityHint="Drag horizontally to preview a date; tap to pin"
            accessibilityActions={[
              { name: 'increment', label: 'Next date' },
              { name: 'decrement', label: 'Previous date' },
            ]}
            onAccessibilityAction={onAccessibilityScrub}
            style={{
              position: 'absolute',
              left: padL,
              right: padR,
              top: padT,
              bottom: padB,
            }}
          />
        ) : null}
      </View>

      {activePoint ? (
        <Row style={{ justifyContent: 'space-between', marginTop: 6 }}>
          <AppText variant="tiny" color="textFaint">
            {activeDate}
          </AppText>
          <AppText variant="tiny" weight="700">
            {activeHighlight != null
              ? pct(activeHighlight)
              : activePoint.min != null && activePoint.max != null
                ? `${pct(activePoint.min)} – ${pct(activePoint.max)}`
                : '—'}
            {activePoint.median != null ? ` · med ${pct(activePoint.median)}` : ''}
            {activePoint.mean != null ? ` · μ ${pct(activePoint.mean)}` : ''}
          </AppText>
        </Row>
      ) : null}
    </View>
  );
}

function CrossMarker({ cx, cy, color }: { cx: number; cy: number; color: string }) {
  if (!Number.isFinite(cx) || !Number.isFinite(cy)) return null;
  return (
    <G>
      <Line x1={cx} y1={cy - 4} x2={cx} y2={cy + 4} stroke={color} strokeWidth={2} />
      <Line x1={cx - 4} y1={cy} x2={cx + 4} y2={cy} stroke={color} strokeWidth={2} />
    </G>
  );
}
