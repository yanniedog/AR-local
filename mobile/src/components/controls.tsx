import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Pressable, Switch, TextInput, View } from 'react-native';

import { hapticSelection } from '../lib/haptics';
import { useTheme } from '../theme/ThemeProvider';
import { androidRipple, AppText } from './ui';

export interface SegOption<T extends string> {
  value: T;
  label: string;
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
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <Pressable
            key={opt.value}
            onPress={() => {
              if (opt.value !== value) hapticSelection();
              onChange(opt.value);
            }}
            accessibilityRole="tab"
            accessibilityLabel={opt.label}
            accessibilityState={{ selected: active }}
            android_ripple={androidRipple(theme.colors.primaryMuted)}
            style={{
              flex: 1,
              paddingVertical: 9,
              minHeight: 48,
              borderRadius: theme.radius.sm,
              backgroundColor: active ? theme.colors.card : 'transparent',
              alignItems: 'center',
              justifyContent: 'center',
              overflow: 'hidden',
              shadowColor: active ? theme.colors.shadow : 'transparent',
              shadowOpacity: active ? 1 : 0,
              shadowRadius: 4,
              shadowOffset: { width: 0, height: 1 },
            }}
          >
            <AppText
              variant="small"
              weight={active ? '700' : '500'}
              color={active ? 'text' : 'textMuted'}
            >
              {opt.label}
            </AppText>
          </Pressable>
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
