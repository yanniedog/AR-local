import { Ionicons } from '@expo/vector-icons';
import { Tabs } from 'expo-router';
import React from 'react';
import { Platform } from 'react-native';

import { BrandLockup } from '../../src/components/BrandLockup';
import { RefreshOutcomeSnackbar } from '../../src/components/feedback';
import { M3NavigationBar } from '../../src/components/M3NavigationBar';
import { getTabIonicon } from '../../src/lib/tabIcons';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function TabsLayout() {
  const theme = useTheme();
  const isAndroid = Platform.OS === 'android';

  return (
    <>
    <Tabs
      tabBar={isAndroid ? (props) => <M3NavigationBar {...props} /> : undefined}
      screenOptions={{
        headerStyle: {
          backgroundColor: isAndroid ? theme.colors.surfaceAlt : theme.colors.surface,
          borderBottomColor: theme.colors.border,
        },
        headerTitleStyle: {
          color: theme.colors.text,
          fontWeight: isAndroid ? '500' : '700',
          letterSpacing: isAndroid ? 0 : -0.3,
          fontSize: isAndroid ? 22 : undefined,
        },
        headerTitleAlign: isAndroid ? 'center' : 'left',
        headerShadowVisible: false,
        sceneStyle: { backgroundColor: theme.colors.bg },
        tabBarActiveTintColor: theme.colors.primary,
        tabBarInactiveTintColor: theme.colors.textMuted,
        tabBarStyle: isAndroid
          ? {
              backgroundColor: theme.colors.surfaceAlt,
              borderTopWidth: 0,
              elevation: 0,
            }
          : {
              backgroundColor: theme.colors.surface,
              borderTopColor: theme.colors.border,
            },
        tabBarLabelStyle: { fontSize: 11, fontWeight: '600' },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'Home',
          headerTitle: () => <BrandLockup markSize={28} />,
          tabBarIcon: isAndroid
            ? () => null
            : ({ color, size }) => <Ionicons name={getTabIonicon('index')!} size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="browse"
        options={{
          title: 'Browse',
          tabBarIcon: isAndroid
            ? () => null
            : ({ color, size }) => <Ionicons name={getTabIonicon('browse')!} size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="watchlist"
        options={{
          title: 'Watchlist',
          tabBarIcon: isAndroid
            ? () => null
            : ({ color, size }) => <Ionicons name={getTabIonicon('watchlist')!} size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="trends"
        options={{
          title: 'Trends',
          tabBarIcon: isAndroid
            ? () => null
            : ({ color, size }) => <Ionicons name={getTabIonicon('trends')!} size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: 'Settings',
          tabBarIcon: isAndroid
            ? () => null
            : ({ color, size }) => <Ionicons name={getTabIonicon('settings')!} size={size} color={color} />,
        }}
      />
    </Tabs>
    <RefreshOutcomeSnackbar />
    </>
  );
}
