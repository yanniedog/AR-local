import React, { useMemo } from 'react';
import { View } from 'react-native';

import { SECTIONS } from '../constants';
import { humanizeEnum } from '../data/format';
import { PROFILE_GROUPS, type ProfileFilters } from '../data/profile';
import { distinctValues } from '../data/selectors';
import { useStore } from '../data/store';
import type { SectionKey } from '../types';
import { useTheme } from '../theme/ThemeProvider';
import { AppText, Chip, Row } from './ui';

/** Chip groups for the saved product profile — shared by onboarding and the Profile screen. */
export function ProfileEditor({
  sections,
  value,
  onChange,
}: {
  sections: SectionKey[];
  value: ProfileFilters;
  onChange: (next: ProfileFilters) => void;
}) {
  const theme = useTheme();
  const core = useStore((s) => s.core);

  const groups = useMemo(
    () =>
      PROFILE_GROUPS.filter((g) => sections.includes(g.section))
        .map((g) => ({
          ...g,
          options: distinctValues(core?.sections?.[g.section]?.rates ?? [], g.field).slice(0, 12),
        }))
        .filter((g) => g.options.length > 0),
    [core, sections],
  );

  const toggle = (key: keyof ProfileFilters, option: string) => {
    const list = value[key];
    onChange({
      ...value,
      [key]: list.includes(option) ? list.filter((v) => v !== option) : [...list, option],
    });
  };

  let prevSection: SectionKey | null = null;
  return (
    <View style={{ gap: 18 }}>
      {groups.map((g) => {
        const showHeader = sections.length > 1 && g.section !== prevSection;
        prevSection = g.section;
        return (
          <View key={`${g.section}-${String(g.key)}`}>
            {showHeader ? (
              <AppText
                variant="tiny"
                weight="700"
                color="textFaint"
                style={{ marginBottom: 8, letterSpacing: 0.6 }}
              >
                {SECTIONS[g.section].title.toUpperCase()}
              </AppText>
            ) : null}
            <AppText variant="small" weight="700" style={{ marginBottom: theme.spacing(2) }}>
              {g.title}
            </AppText>
            <Row gap={8} style={{ flexWrap: 'wrap' }}>
              {g.options.map((o) => (
                <Chip
                  key={o}
                  label={humanizeEnum(o)}
                  selected={value[g.key].includes(o)}
                  onPress={() => toggle(g.key, o)}
                />
              ))}
            </Row>
          </View>
        );
      })}
    </View>
  );
}
