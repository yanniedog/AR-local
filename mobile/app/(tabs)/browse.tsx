import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import React, { useCallback, useEffect, useMemo } from 'react';
import { Pressable, View } from 'react-native';

import { HierarchyView } from '../../src/components/HierarchyView';
import { CompactToggle, SegmentedControl } from '../../src/components/controls';
import { Screen } from '../../src/components/Screen';
import { AppText, Row } from '../../src/components/ui';
import { SECTIONS, sectionFromSlug } from '../../src/constants';
import { resolveInterestSection, sectionSegmentOptions } from '../../src/data/interests';
import { breadcrumb } from '../../src/data/taxonomy';
import { useStore } from '../../src/data/store';
import { openBrowseDrill, openHierarchy, openSearch } from '../../src/lib/nav';
import type { SectionKey } from '../../src/types';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function Browse() {
  const theme = useTheme();
  const core = useStore((s) => s.core);
  const params = useLocalSearchParams<{ section?: string; path?: string }>();
  const interests = useStore((s) => s.prefs.interests);
  const section = useStore((s) => s.activeSection);
  const setActiveSection = useStore((s) => s.setActiveSection);
  const includeNonStandard = useStore((s) => s.prefs.includeNonStandard);
  const setPref = useStore((s) => s.setPref);
  const sectionOptions = useMemo(() => sectionSegmentOptions(interests), [interests]);

  const routedSection = params.section ? sectionFromSlug(params.section) : undefined;
  const drillPath = useMemo(() => (params.path ?? '').split('.').filter(Boolean), [params.path]);
  const crumbs = useMemo(() => breadcrumb(section, drillPath), [section, drillPath]);

  useEffect(() => {
    const resolved = resolveInterestSection(interests, section);
    if (resolved !== section) setActiveSection(resolved);
  }, [interests, section, setActiveSection]);

  // Honour deep-links (e.g. Home category tap, Trends -> openBrowse) when route params change.
  useEffect(() => {
    if (routedSection) setActiveSection(resolveInterestSection(interests, routedSection));
  }, [routedSection, interests, setActiveSection]);

  const onSectionChange = useCallback(
    (next: SectionKey) => {
      setActiveSection(next);
      openBrowseDrill(next, []);
    },
    [setActiveSection],
  );

  if (!core) return null;

  const title = crumbs[crumbs.length - 1] || SECTIONS[section].title;

  return (
    <Screen>
      <View style={{ paddingHorizontal: 16, paddingTop: 12 }}>
        <Row gap={10}>
          <View style={{ flex: 1 }}>
            {sectionOptions.length > 1 ? (
              <SegmentedControl options={sectionOptions} value={section} onChange={onSectionChange} />
            ) : null}
          </View>
          <Pressable
            onPress={() => openHierarchy(section, drillPath)}
            style={{
              backgroundColor: theme.colors.surfaceAlt,
              borderRadius: theme.radius.md,
              paddingHorizontal: 12,
              height: 44,
              justifyContent: 'center',
            }}
            accessibilityLabel="Browse taxonomy tree"
          >
            <Ionicons name="git-network-outline" size={20} color={theme.colors.text} />
          </Pressable>
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
        {drillPath.length ? (
          <AppText variant="tiny" color="textFaint" numberOfLines={2} style={{ marginTop: 10 }}>
            {title} · {crumbs.join('  ›  ')}
          </AppText>
        ) : null}
      </View>
      <View style={{ flex: 1 }}>
        <HierarchyView key={`${section}-${drillPath.join('.')}`} section={section} path={drillPath} />
      </View>
    </Screen>
  );
}
