import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  type PressableProps,
  StyleSheet,
  Text,
  type TextProps,
  View,
  type ViewProps,
  type ViewStyle,
} from 'react-native';

import type { Palette } from '../theme/colors';
import { useTheme } from '../theme/ThemeProvider';

type FontVariant = 'h1' | 'h2' | 'h3' | 'body' | 'small' | 'tiny';

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
      style={[
        { color: theme.colors[color], fontSize: theme.font[variant], fontWeight: weight },
        variant === 'h1' && { fontWeight: '800', letterSpacing: -0.5 },
        variant === 'h2' && { fontWeight: '700', letterSpacing: -0.3 },
        variant === 'h3' && { fontWeight: '700' },
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
        opacity: pressed ? 0.7 : 1,
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
}: {
  title: string;
  onPress?: () => void;
  variant?: 'primary' | 'secondary' | 'ghost';
  icon?: keyof typeof Ionicons.glyphMap;
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
}) {
  const theme = useTheme();
  const bg =
    variant === 'primary'
      ? theme.colors.primary
      : variant === 'secondary'
        ? theme.colors.chip
        : 'transparent';
  const fg = variant === 'primary' ? theme.colors.onPrimary : theme.colors.text;
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
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
          opacity: pressed || disabled ? 0.6 : 1,
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
      onPress={onPress}
      hitSlop={10}
      accessibilityLabel={accessibilityLabel}
      style={({ pressed }) => [{ padding: 6, opacity: pressed ? 0.6 : 1 }, style]}
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
