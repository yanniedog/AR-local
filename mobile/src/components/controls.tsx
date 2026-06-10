import { Ionicons } from '@expo/vector-icons';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  type LayoutChangeEvent,
  Pressable,
  Switch,
  TextInput,
  type StyleProp,
  View,
  type ViewStyle,
} from 'react-native';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSequence,
  withSpring,
  withTiming,
} from 'react-native-reanimated';

import { hapticSelection } from '../lib/haptics';
import { useTheme } from '../theme/ThemeProvider';
import { TouchTarget } from './TouchTarget';
import { androidRipple, AppText } from './ui';

const PILL_SPRING = { damping: 20, stiffness: 280, mass: 0.8 };

export interface SegOption<T extends string> {
  value: T;
  label: string;
}

type SegmentLayout = { x: number; width: number };

/** Brief opacity dip when `section` changes — keeps content mounted (no hard remount). */
export function SectionCrossfade({
  section,
  children,
  style,
}: {
  section: string;
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
}) {
  const opacity = useSharedValue(1);
  const mounted = useRef(false);

  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    opacity.value = withSequence(
      withTiming(0.22, { duration: 90 }),
      withTiming(1, { duration: 200 }),
    );
  }, [section, opacity]);

  const animatedStyle = useAnimatedStyle(() => ({ opacity: opacity.value }));
  return <Animated.View style={[style, animatedStyle]}>{children}</Animated.View>;
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
}: {
  options: SegOption<T>[];
  value: T;
  onChange: (v: T) => void;
}) {
  const theme = useTheme();
  const [layouts, setLayouts] = useState<Partial<Record<T, SegmentLayout>>>({});
  const pillX = useSharedValue(0);
  const pillW = useSharedValue(0);
  const pillReady = useRef(false);

  const movePill = useCallback(
    (layout: SegmentLayout, animate: boolean) => {
      if (animate) {
        pillX.value = withSpring(layout.x, PILL_SPRING);
        pillW.value = withSpring(layout.width, PILL_SPRING);
      } else {
        pillX.value = layout.x;
        pillW.value = layout.width;
      }
    },
    [pillW, pillX],
  );

  useEffect(() => {
    const layout = layouts[value];
    if (!layout) return;
    movePill(layout, pillReady.current);
    pillReady.current = true;
  }, [value, layouts, movePill]);

  const onSegmentLayout = useCallback((optValue: T, e: LayoutChangeEvent) => {
    const { x, width } = e.nativeEvent.layout;
    setLayouts((prev) => {
      const existing = prev[optValue];
      if (existing?.x === x && existing?.width === width) return prev;
      return { ...prev, [optValue]: { x, width } };
    });
  }, []);

  const pillStyle = useAnimatedStyle(() => ({
    position: 'absolute',
    top: 3,
    bottom: 3,
    left: pillX.value,
    width: pillW.value,
    borderRadius: theme.radius.sm,
    backgroundColor: theme.colors.card,
    shadowColor: theme.colors.shadow,
    shadowOpacity: 1,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 1 },
  }));

  return (
    <View
      accessibilityRole="tablist"
      style={{
        flexDirection: 'row',
        backgroundColor: theme.colors.surfaceAlt,
        borderRadius: theme.radius.md,
        padding: 3,
      }}
    >
      <Animated.View pointerEvents="none" style={pillStyle} />
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <TouchTarget
            key={opt.value}
            onPress={() => {
              if (opt.value !== value) hapticSelection();
              onChange(opt.value);
            }}
            onLayout={(e) => onSegmentLayout(opt.value, e)}
            accessibilityRole="tab"
            accessibilityLabel={opt.label}
            accessibilityState={{ selected: active }}
            android_ripple={androidRipple(theme.colors.primaryMuted)}
            style={{
              flex: 1,
              borderRadius: theme.radius.sm,
              alignItems: 'center',
              justifyContent: 'center',
              overflow: 'hidden',
            }}
          >
            <AppText
              variant="small"
              weight={active ? '700' : '500'}
              color={active ? 'text' : 'textMuted'}
              numberOfLines={1}
            >
              {opt.label}
            </AppText>
          </TouchTarget>
        );
      })}
    </View>
  );
}

export function SearchBar({
  value,
  onChangeText,
  placeholder = 'Search products or banks',
}: {
  value: string;
  onChangeText: (t: string) => void;
  placeholder?: string;
}) {
  const theme = useTheme();
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        backgroundColor: theme.colors.surfaceAlt,
        borderRadius: theme.radius.md,
        paddingHorizontal: 12,
        height: 44,
      }}
    >
      <Ionicons name="search" size={18} color={theme.colors.textFaint} />
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={theme.colors.textFaint}
        style={{ flex: 1, color: theme.colors.text, fontSize: theme.font.body }}
        autoCorrect={false}
        autoCapitalize="none"
        clearButtonMode="while-editing"
        returnKeyType="search"
      />
      {value.length > 0 ? (
        <Pressable
          onPress={() => onChangeText('')}
          hitSlop={8}
          android_ripple={androidRipple(theme.colors.primaryMuted, true)}
          style={{ borderRadius: theme.radius.sm, overflow: 'hidden' }}
        >
          <Ionicons name="close-circle" size={18} color={theme.colors.textFaint} />
        </Pressable>
      ) : null}
    </View>
  );
}

export function CompactToggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (value: boolean) => void;
}) {
  const theme = useTheme();
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 10,
        minHeight: 40,
        paddingHorizontal: 12,
        backgroundColor: theme.colors.surfaceAlt,
        borderRadius: theme.radius.md,
      }}
    >
      <AppText variant="small" weight="600" color="textMuted">
        {label}
      </AppText>
      <Switch
        value={value}
        onValueChange={onChange}
        trackColor={{ true: theme.colors.primary, false: theme.colors.border }}
        thumbColor={value ? theme.colors.card : undefined}
        accessibilityLabel={label}
      />
    </View>
  );
}
