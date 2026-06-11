import { Ionicons } from '@expo/vector-icons';
import { router, type Href } from 'expo-router';
import React from 'react';
import { Modal, Pressable, ScrollView, View } from 'react-native';
import Animated, { FadeIn, SlideInLeft } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { getInstalledAppInfo } from '../lib/appUpdate';
import { useStore } from '../data/store';
import { useTheme } from '../theme/ThemeProvider';
import { BrandLockup } from './BrandLockup';
import { AppText, Divider } from './ui';

export interface SideMenuItem {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  route: Href;
}

export interface SideMenuSection {
  title: string;
  items: SideMenuItem[];
}

/** Exported for tests; single source of truth for sidebar destinations. */
export const MENU_SECTIONS: SideMenuSection[] = [
  {
    title: 'Rates',
    items: [
      { icon: 'home', label: 'Home', route: '/' },
      { icon: 'grid', label: 'Browse', route: '/browse' },
      { icon: 'star', label: 'Watchlist', route: '/watchlist' },
      { icon: 'pulse', label: 'Trends', route: '/trends' },
    ],
  },
  {
    title: 'Explore',
    items: [
      { icon: 'business', label: 'Lenders', route: '/banks' },
      { icon: 'search', label: 'Search', route: '/search' },
      { icon: 'git-compare', label: 'Compare', route: '/compare' },
    ],
  },
  {
    title: 'App',
    items: [
      { icon: 'settings', label: 'Settings', route: '/settings' },
      { icon: 'document-text', label: 'Terms', route: '/terms' },
      { icon: 'bug', label: 'Debug log', route: '/debug-log' },
    ],
  },
];

/** Hamburger-opened navigation sidebar (left slide-in over the current screen). */
export function SideMenu({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const diagnosticsEnabled = useStore((s) => s.prefs.diagnosticsEnabled);

  const sections = diagnosticsEnabled
    ? MENU_SECTIONS
    : MENU_SECTIONS.map((section) =>
        section.title === 'App'
          ? { ...section, items: section.items.filter((item) => item.route !== '/debug-log') }
          : section,
      );

  const go = (route: Href) => {
    onClose();
    router.navigate(route);
  };

  return (
    <Modal visible={visible} transparent animationType="none" onRequestClose={onClose}>
      <View style={{ flex: 1, flexDirection: 'row' }}>
        <Animated.View
          entering={SlideInLeft.duration(180)}
          style={{
            width: 290,
            maxWidth: '82%',
            backgroundColor: theme.colors.surface,
            borderRightColor: theme.colors.border,
            borderRightWidth: 1,
            paddingTop: insets.top + 14,
            paddingBottom: insets.bottom + 10,
          }}
        >
          <View style={{ paddingHorizontal: 16, marginBottom: 10 }}>
            <BrandLockup markSize={26} />
          </View>
          <Divider />
          <ScrollView contentContainerStyle={{ paddingVertical: 6 }}>
            {sections.map((section, si) => (
              <View key={section.title}>
                {si > 0 ? <Divider style={{ marginVertical: 6 }} /> : null}
                <AppText
                  variant="tiny"
                  weight="700"
                  color="textFaint"
                  style={{ paddingHorizontal: 16, paddingVertical: 6 }}
                >
                  {section.title.toUpperCase()}
                </AppText>
                {section.items.map((item) => (
                  <Pressable
                    key={item.label}
                    onPress={() => go(item.route)}
                    accessibilityRole="button"
                    accessibilityLabel={item.label}
                    style={({ pressed }) => ({
                      flexDirection: 'row',
                      alignItems: 'center',
                      gap: 14,
                      paddingHorizontal: 16,
                      paddingVertical: 12,
                      backgroundColor: pressed ? theme.colors.surfaceAlt : 'transparent',
                    })}
                  >
                    <Ionicons name={item.icon} size={20} color={theme.colors.primary} />
                    <AppText variant="body" weight="600">
                      {item.label}
                    </AppText>
                  </Pressable>
                ))}
              </View>
            ))}
          </ScrollView>
          <Divider />
          <AppText variant="tiny" color="textFaint" style={{ paddingHorizontal: 16, paddingTop: 8 }}>
            Australian Rates v{getInstalledAppInfo().version}
          </AppText>
        </Animated.View>
        <Animated.View entering={FadeIn.duration(180)} style={{ flex: 1 }}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Close menu"
            onPress={onClose}
            style={{ flex: 1, backgroundColor: '#00000066' }}
          />
        </Animated.View>
      </View>
    </Modal>
  );
}
