import React from 'react';
import { View } from 'react-native';

import { ProfileEditor } from '../src/components/ProfileEditor';
import { ScreenScrollView } from '../src/components/Screen';
import { AppText, Button, Card } from '../src/components/ui';
import { EMPTY_PROFILE, profileSelectionCount } from '../src/data/profile';
import { useStore } from '../src/data/store';
import { useTheme } from '../src/theme/ThemeProvider';

export default function Profile() {
  const theme = useTheme();
  const interests = useStore((s) => s.prefs.interests);
  const profileFilters = useStore((s) => s.prefs.profileFilters);
  const setPref = useStore((s) => s.setPref);
  const count = profileSelectionCount(profileFilters);

  return (
    <ScreenScrollView contentContainerStyle={{ padding: 16, paddingBottom: 32 }}>
      <AppText variant="body" color="textMuted" style={{ marginBottom: 16, lineHeight: 22 }}>
        Pick the product attributes that match your situation — owner-occupied, P&I, your LVR,
        and so on. They apply automatically as filters across the app, so you never have to
        re-select them. Leave a group empty to see everything.
      </AppText>
      <Card>
        <ProfileEditor
          sections={interests}
          value={profileFilters}
          onChange={(next) => setPref('profileFilters', next)}
        />
      </Card>
      {count > 0 ? (
        <View style={{ marginTop: theme.spacing(4) }}>
          <Button
            title={`Clear profile (${count} selected)`}
            variant="ghost"
            onPress={() => setPref('profileFilters', { ...EMPTY_PROFILE })}
          />
        </View>
      ) : null}
    </ScreenScrollView>
  );
}
