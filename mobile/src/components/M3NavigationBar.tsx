import type { BottomTabBarProps } from '@react-navigation/bottom-tabs';
import React from 'react';
import { Pressable, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { M3_NAV_BAR_HEIGHT } from '../lib/androidChrome';
import { hapticSelection } from '../lib/haptics';
import { getTabLabel, getTabMaterialSymbol } from '../lib/tabIcons';
import { useTheme } from '../theme/ThemeProvider';
import { MaterialSymbol } from './MaterialSymbol';

/** Material Design 3 bottom navigation bar with active indicator pill (Android). */
export function M3NavigationBar({ state, descriptors, navigation }: BottomTabBarProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <View
      style={{
        flexDirection: 'row',
        backgroundColor: theme.colors.surfaceAlt,
        height: M3_NAV_BAR_HEIGHT + insets.bottom,
        paddingBottom: insets.bottom,
        paddingTop: 8,
      }}
    >
      {state.routes.map((route, index) => {
        const focused = state.index === index;
        const { options } = descriptors[route.key];
        const label = getTabLabel(route.name, options.title);
        const symbol = getTabMaterialSymbol(route.name);

        const onPress = () => {
          const event = navigation.emit({
            type: 'tabPress',
            target: route.key,
            canPreventDefault: true,
          });
          if (focused) {
            hapticSelection();
            return;
          }
          if (!event.defaultPrevented) {
            navigation.navigate(route.name, route.params);
          }
        };

        const onLongPress = () => {
          navigation.emit({ type: 'tabLongPress', target: route.key });
        };

        return (
          <Pressable
            key={route.key}
            accessibilityRole="tab"
            accessibilityState={{ selected: focused }}
            accessibilityLabel={options.tabBarAccessibilityLabel ?? label}
            onPress={onPress}
            onLongPress={onLongPress}
            style={{ flex: 1, alignItems: 'center', justifyContent: 'center', minHeight: 48 }}
          >
            <View
              style={{
                alignItems: 'center',
                justifyContent: 'center',
                paddingHorizontal: 16,
                paddingVertical: 4,
                borderRadius: theme.radius.pill,
                backgroundColor: focused ? theme.colors.primaryMuted : 'transparent',
                minWidth: 64,
              }}
            >
              {symbol ? (
                <MaterialSymbol
                  name={symbol}
                  filled={focused}
                  size={24}
                  color={focused ? theme.colors.primary : theme.colors.textMuted}
                />
              ) : null}
              <Text
                numberOfLines={1}
                style={{
                  marginTop: 4,
                  fontSize: 12,
                  fontWeight: focused ? '600' : '500',
                  color: focused ? theme.colors.primary : theme.colors.textMuted,
                }}
              >
                {label}
              </Text>
            </View>
          </Pressable>
        );
      })}
    </View>
  );
}
