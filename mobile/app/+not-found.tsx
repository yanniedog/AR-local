import { Link, Stack } from 'expo-router';
import React from 'react';
import { View } from 'react-native';

import { AppText } from '../src/components/ui';
import { useTheme } from '../src/theme/ThemeProvider';

export default function NotFound() {
  const theme = useTheme();
  return (
    <>
      <Stack.Screen options={{ title: 'Not found' }} />
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, backgroundColor: theme.colors.bg }}>
        <AppText variant="h2">This screen doesn&apos;t exist</AppText>
        <Link href="/(tabs)" style={{ marginTop: 16 }}>
          <AppText variant="body" style={{ color: theme.colors.primary }} weight="700">
            Go to Home
          </AppText>
        </Link>
      </View>
    </>
  );
}
