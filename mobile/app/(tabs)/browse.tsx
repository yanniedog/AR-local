import { useLocalSearchParams } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { View } from 'react-native';

import { HierarchyView } from '../../src/components/HierarchyView';
import { Screen, screenEdgeStyle } from '../../src/components/Screen';
import { ToolbarIconButton } from '../../src/components/ToolbarIconButton';
import { CompactToggle, SegmentedControl } from '../../src/components/controls';
import { Row } from '../../src/components/ui';
import { sectionFromSlug } from '../../src/constants';
import { useStore } from '../../src/data/store';
import { openHierarchy, openSearch } from '../../src/lib/nav';
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
  const params = useLocalSearchParams<{ section?: string }>();
  const defaultSection = useStore((s) => s.prefs.defaultSection);
  const includeNonStandard = useStore((s) => s.prefs.includeNonStandard);
  const setPref = useStore((s) => s.setPref);
  const routed = params.section ? sectionFromSlug(params.section) : undefined;
  const [section, setSection] = useState<SectionKey>(routed ?? defaultSection);

  useEffect(() => {
    const r = params.section ? sectionFromSlug(params.section) : undefined;
    if (r && r !== section) setSection(r);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.section]);

  if (!core) return null;

  return (
    <Screen>
      <View style={screenEdgeStyle(theme)}>
        <Row gap={theme.spacing(3)}>
          <View style={{ flex: 1 }}>
            <SegmentedControl options={SECTION_SEG} value={section} onChange={setSection} />
          </View>
          <ToolbarIconButton
            icon="git-network-outline"
            onPress={() => openHierarchy(section)}
            accessibilityLabel="Browse taxonomy tree"
          />
          <ToolbarIconButton icon="search" onPress={() => openSearch(section)} accessibilityLabel="Search products" />
        </Row>
        <CompactToggle
          label="Include non-standard accounts"
          value={includeNonStandard}
          onChange={(value) => setPref('includeNonStandard', value)}
        />
      </View>
      <View style={{ flex: 1 }}>
        <HierarchyView key={section} section={section} path={[]} />
      </View>
    </Screen>
  );
}
