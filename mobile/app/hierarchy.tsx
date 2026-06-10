import { Ionicons } from '@expo/vector-icons';
import { Stack, useLocalSearchParams } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { Pressable, View } from 'react-native';

import { CompactToggle, SegmentedControl } from '../src/components/controls';
import { Screen } from '../src/components/Screen';
import { TaxonomyTreeView } from '../src/components/TaxonomyTreeView';
import { Row } from '../src/components/ui';
import { sectionFromSlug } from '../src/constants';
import { useStore } from '../src/data/store';
import { openSearch } from '../src/lib/nav';
import type { SectionKey } from '../src/types';
import { useTheme } from '../src/theme/ThemeProvider';

const SECTION_SEG = [
  { value: 'Mortgage' as SectionKey, label: 'Mortgage' },
  { value: 'Savings' as SectionKey, label: 'Savings' },
  { value: 'TD' as SectionKey, label: 'Term Deps' },
];

export default function HierarchyScreen() {
  const theme = useTheme();
  const core = useStore((s) => s.core);
  const params = useLocalSearchParams<{ section?: string; path?: string }>();
  const defaultSection = useStore((s) => s.prefs.defaultSection);
  const includeNonStandard = useStore((s) => s.prefs.includeNonStandard);
  const setPref = useStore((s) => s.setPref);
  const routed = params.section ? sectionFromSlug(params.section) : undefined;
  const initialPath = (params.path ?? '').split('.').filter(Boolean);
  const [section, setSection] = useState<SectionKey>(routed ?? defaultSection);

  useEffect(() => {
    const r = params.section ? sectionFromSlug(params.section) : undefined;
    if (r && r !== section) setSection(r);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.section]);

  if (!core) return null;

  return (
    <Screen>
      <Stack.Screen options={{ title: 'Browse tree' }} />
      <View style={{ paddingHorizontal: 16, paddingTop: 12 }}>
        <Row gap={10}>
          <View style={{ flex: 1 }}>
            <SegmentedControl options={SECTION_SEG} value={section} onChange={setSection} />
          </View>
          <Pressable
            onPress={() => openSearch(section)}
            style={{
              backgroundColor: theme.colors.surfaceAlt,
              borderRadius: theme.radius.md,
              paddingHorizontal: 12,
              height: 44,
              justifyContent: 'center',
            }}
            accessibilityLabel="Search products"
          >
            <Ionicons name="search" size={20} color={theme.colors.text} />
          </Pressable>
        </Row>
        <View style={{ marginTop: 10 }}>
          <CompactToggle
            label="Include non-standard accounts"
            value={includeNonStandard}
            onChange={(value) => setPref('includeNonStandard', value)}
          />
        </View>
      </View>
      <View style={{ flex: 1 }}>
        <TaxonomyTreeView key={`${section}-${params.path ?? ''}`} section={section} initialPath={initialPath} />
      </View>
    </Screen>
  );
}
