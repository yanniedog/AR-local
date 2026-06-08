import { Ionicons } from '@expo/vector-icons';
import React, { useState } from 'react';
import { Pressable, View } from 'react-native';

import { HierarchyView } from '../../src/components/HierarchyView';
import { SegmentedControl } from '../../src/components/controls';
import { Row } from '../../src/components/ui';
import { useStore } from '../../src/data/store';
import { openSearch } from '../../src/lib/nav';
import type { SectionKey } from '../../src/types';
import { useTheme } from '../../src/theme/ThemeProvider';

const SECTION_SEG = [
  { value: 'Mortgage' as SectionKey, label: 'Loans' },
  { value: 'Savings' as SectionKey, label: 'Savings' },
  { value: 'TD' as SectionKey, label: 'Deposits' },
];

export default function Browse() {
  const theme = useTheme();
  const core = useStore((s) => s.core);
  const defaultSection = useStore((s) => s.prefs.defaultSection);
  const [section, setSection] = useState<SectionKey>(defaultSection);

  if (!core) return null;

  return (
    <View style={{ flex: 1, backgroundColor: theme.colors.bg }}>
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
      </View>
      <View style={{ flex: 1 }}>
        {/* key forces a fresh drill-down root when the section changes */}
        <HierarchyView key={section} section={section} path={[]} />
      </View>
    </View>
  );
}
