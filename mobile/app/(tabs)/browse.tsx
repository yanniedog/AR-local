import { router, useLocalSearchParams } from 'expo-router';
import React, { useEffect, useMemo } from 'react';
import { View } from 'react-native';

import { HierarchyView } from '../../src/components/HierarchyView';
import { Screen, screenEdgeStyle } from '../../src/components/Screen';
import { ToolbarIconButton } from '../../src/components/ToolbarIconButton';
import { SegmentedControl } from '../../src/components/controls';
import { Row } from '../../src/components/ui';
import { sectionFromSlug } from '../../src/constants';
import { resolveInterestSection, sectionSegmentOptions } from '../../src/data/interests';
import { useStore } from '../../src/data/store';
import { checkDrillOutcome, logNavParamDrop } from '../../src/lib/degradationLog';
import { openHierarchy, openSearch, parseBrowsePath } from '../../src/lib/nav';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function Browse() {
  const theme = useTheme();
  const core = useStore((s) => s.core);
  const params = useLocalSearchParams<{ section?: string; path?: string | string[] }>();
  const drillPath = useMemo(() => parseBrowsePath(params.path), [params.path]);
  const interests = useStore((s) => s.prefs.interests);
  const section = useStore((s) => s.activeSection);
  const setActiveSection = useStore((s) => s.setActiveSection);
  const sectionOptions = useMemo(() => sectionSegmentOptions(interests), [interests]);

  useEffect(() => {
    const resolved = resolveInterestSection(interests, section);
    if (resolved !== section) setActiveSection(resolved);
  }, [interests, section, setActiveSection]);

  useEffect(() => {
    const slug = params.section;
    const r = slug ? sectionFromSlug(slug) : undefined;
    if (slug && !r) logNavParamDrop({ screen: 'browse', param: 'section', actual: String(Array.isArray(slug) ? slug[0] : slug) });
    if (r) setActiveSection(resolveInterestSection(interests, r));
  }, [params.section, interests, setActiveSection]);

  useEffect(() => {
    checkDrillOutcome(section, drillPath);
  }, [section, drillPath]);

  if (!core) return null;

  return (
    <Screen>
      <View style={screenEdgeStyle(theme)}>
        <Row gap={theme.spacing(3)}>
          <View style={{ flex: 1 }}>
            {sectionOptions.length > 1 ? (
              <SegmentedControl options={sectionOptions} value={section} onChange={setActiveSection} />
            ) : null}
          </View>
          <ToolbarIconButton
            icon="git-network-outline"
            onPress={() => openHierarchy(section, drillPath)}
            accessibilityLabel="Browse taxonomy tree"
          />
          <ToolbarIconButton
            icon="business-outline"
            onPress={() => router.push('/banks')}
            accessibilityLabel="Browse lenders"
            accessibilityHint="Opens searchable lender directory"
          />
          <ToolbarIconButton icon="search" onPress={() => openSearch(section)} accessibilityLabel="Search products" />
        </Row>
      </View>
      <View style={{ flex: 1 }}>
        <HierarchyView key={`${section}-${drillPath.join('.')}`} section={section} path={drillPath} />
      </View>
    </Screen>
  );
}
