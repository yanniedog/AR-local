import { Stack, useLocalSearchParams } from 'expo-router';
import React from 'react';
import { View } from 'react-native';

import { HierarchyView } from '../src/components/HierarchyView';
import { AppText } from '../src/components/ui';
import { SECTIONS, SECTION_ORDER } from '../src/constants';
import { breadcrumb } from '../src/data/taxonomy';
import type { SectionKey } from '../src/types';
import { useTheme } from '../src/theme/ThemeProvider';

export default function NodeScreen() {
  const theme = useTheme();
  const { section: secRaw, path: pathRaw } = useLocalSearchParams<{ section: string; path?: string }>();
  const section = (SECTION_ORDER.includes(secRaw as SectionKey) ? secRaw : 'Mortgage') as SectionKey;
  const path = (pathRaw ?? '').split('.').filter(Boolean);
  const crumbs = breadcrumb(section, path);
  const title = crumbs[crumbs.length - 1] || SECTIONS[section].title;

  return (
    <View style={{ flex: 1, backgroundColor: theme.colors.bg }}>
      <Stack.Screen options={{ title }} />
      <View style={{ paddingHorizontal: 16, paddingTop: 10 }}>
        <AppText variant="tiny" color="textFaint" numberOfLines={1}>
          {crumbs.join('  ›  ')}
        </AppText>
      </View>
      <View style={{ flex: 1 }}>
        <HierarchyView section={section} path={path} />
      </View>
    </View>
  );
}
