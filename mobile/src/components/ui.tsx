import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  type PressableProps,
  StyleSheet,
  Text,
  type TextProps,
  View,
  type ViewProps,
  type ViewStyle,
} from 'react-native';

import { hapticLightImpact, hapticSelection } from '../lib/haptics';
import type { Palette } from '../theme/colors';
import type { FontVariant } from '../theme/theme';
import { useTheme } from '../theme/ThemeProvider';

const VARIANT_WEIGHT: Partial<Record<FontVariant, '700' | '800'>> = {
  h1: '800',
  h2: '700',
  h3: '700',
  rate: '700',
  rateHero: '700',
};

function maxFontSizeMultiplierFor(variant: FontVariant): number {
  return variant === 'tiny' || variant === 'small' || variant === 'rate' ? 1.2 : 1.35;
}

export function androidRipple(color: string, borderless = false) {
  return Platform.OS === 'android' ? { color, borderless } : undefined;
}

function pressedOpacity(pressed: boolean, amount = 0.7): { opacity: number } | Record<string, never> {
  return Platform.OS !== 'android' && pressed ? { opacity: amount } : {};
}

export function AppText({
  variant = 'body',
  color = 'text',
  weight,
  style,
  ...rest
}: TextProps & {
  variant?: FontVariant;
  color?: keyof Palette;
  weight?: '400' | '500' | '600' | '700' | '800';
}) {
  const theme = useTheme();
  return (
    <Text
      allowFontScaling
      maxFontSizeMultiplier={maxFontSizeMultiplierFor(variant)}
      style={[
        {
          color: theme.colors[color],
          fontSize: theme.font[variant],
          lineHeight: theme.lineHeight[variant],
          fontWeight: weight ?? VARIANT_WEIGHT[variant],
        },
        variant === 'h1' && { letterSpacing: -0.5 },
        variant === 'h2' && { letterSpacing: -0.3 },
        variant === 'rateHero' && { letterSpacing: -0.5 },
        (variant === 'rate' || variant === 'rateHero') && { fontVariant: ['tabular-nums'] },
        style,
      ]}
      {...rest}
    />
  );
}

export function Card({ style, children, ...rest }: ViewProps) {
  const theme = useTheme();
  return (
    <View
      style={[
        {
          backgroundColor: theme.colors.card,
          borderRadius: theme.radius.lg,
          borderWidth: StyleSheet.hairlineWidth,
          borderColor: theme.colors.border,
          padding: theme.spacing(4),
        },
        style,
      ]}
      {...rest}
    >
      {children}
    </View>
  );
}

export function Row({ style, gap = 8, ...rest }: ViewProps & { gap?: number }) {
  return <View style={[{ flexDirection: 'row', alignItems: 'center', gap }, style]} {...rest} />;
}

export function Divider({ style }: { style?: ViewStyle }) {
  const theme = useTheme();
  return (
    <View style={[{ height: StyleSheet.hairlineWidth, backgroundColor: theme.colors.border }, style]} />
  );
}

export function Chip({
  label,
  selected,
  onPress,
  icon,
}: {
  label: string;
  selected?: boolean;
  onPress?: () => void;
  icon?: keyof typeof Ionicons.glyphMap;
}) {
  const theme = useTheme();
  return (
    <Pressable
      onPress={onPress}
      android_ripple={androidRipple(theme.colors.primaryMuted)}
      style={({ pressed }) => ({
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        paddingHorizontal: 12,
        paddingVertical: 7,
        borderRadius: theme.radius.pill,
        borderWidth: 1,
        borderColor: selected ? theme.colors.primary : theme.colors.border,
        backgroundColor: selected ? theme.colors.primaryMuted : theme.colors.chip,
        overflow: 'hidden',
        ...pressedOpacity(pressed, 0.7),
      })}
    >
      {icon ? (
        <Ionicons
          name={icon}
          size={14}
          color={selected ? theme.colors.primary : theme.colors.chipText}
        />
      ) : null}
      <Text
        style={{
          color: selected ? theme.colors.primary : theme.colors.chipText,
          fontWeight: selected ? '700' : '500',
          fontSize: theme.font.small,
        }}
      >
        {label}
      </Text>
    </Pressable>
  );
}

export function Button({
  title,
  onPress,
  variant = 'primary',
  icon,
  loading,
  disabled,
  style,
  hapticOnPress,
}: {
  title: string;
  onPress?: () => void;
  variant?: 'primary' | 'secondary' | 'ghost';
  icon?: keyof typeof Ionicons.glyphMap;
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
  /** Light impact on press (e.g. filter Apply). */
  hapticOnPress?: boolean;
}) {
  const theme = useTheme();
  const bg =
    variant === 'primary'
      ? theme.colors.primary
      : variant === 'secondary'
        ? theme.colors.chip
        : 'transparent';
  const fg = variant === 'primary' ? theme.colors.onPrimary : theme.colors.text;
  const rippleColor =
    variant === 'primary' ? theme.colors.onPrimary : theme.colors.primaryMuted;
  return (
    <Pressable
      onPress={() => {
        if (hapticOnPress) hapticLightImpact();
        onPress?.();
      }}
      disabled={disabled || loading}
      android_ripple={androidRipple(rippleColor, variant === 'ghost')}
      style={({ pressed }) => [
        {
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 8,
          paddingHorizontal: 18,
          paddingVertical: 13,
          borderRadius: theme.radius.md,
          backgroundColor: bg,
          borderWidth: variant === 'ghost' ? 1 : 0,
          borderColor: theme.colors.border,
          overflow: 'hidden',
          ...(disabled ? { opacity: 0.6 } : pressedOpacity(pressed, 0.85)),
        },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <>
          {icon ? <Ionicons name={icon} size={18} color={fg} /> : null}
          <Text style={{ color: fg, fontWeight: '700', fontSize: theme.font.body }}>{title}</Text>
        </>
      )}
    </Pressable>
  );
}

export function IconButton({
  icon,
  onPress,
  color,
  size = 22,
  accessibilityLabel,
  style,
  ...rest
}: PressableProps & {
  icon: keyof typeof Ionicons.glyphMap;
  onPress?: () => void;
  color?: keyof Palette;
  size?: number;
  style?: ViewStyle;
}) {
  const theme = useTheme();
  return (
    <Pressable
      onPress={() => {
        hapticSelection();
        onPress?.();
      }}
      hitSlop={10}
      accessibilityLabel={accessibilityLabel}
      android_ripple={androidRipple(theme.colors.primaryMuted, true)}
      style={({ pressed }) => [
        { padding: 6, borderRadius: theme.radius.sm, overflow: 'hidden', ...pressedOpacity(pressed, 0.6) },
        style,
      ]}
      {...rest}
    >
      <Ionicons name={icon} size={size} color={theme.colors[color ?? 'text']} />
    </Pressable>
  );
}

export function Badge({ label, tone = 'muted' }: { label: string; tone?: 'muted' | 'success' | 'warning' | 'danger' | 'primary' }) {
  const theme = useTheme();
  const map: Record<string, string> = {
    muted: theme.colors.chipText,
    success: theme.colors.success,
    warning: theme.colors.warning,
    danger: theme.colors.danger,
    primary: theme.colors.primary,
  };
  return (
    <View
      style={{
        paddingHorizontal: 8,
        paddingVertical: 3,
        borderRadius: theme.radius.sm,
        backgroundColor: theme.colors.chip,
      }}
    >
      <Text style={{ color: map[tone], fontSize: theme.font.tiny, fontWeight: '700' }}>{label}</Text>
    </View>
  );
}
