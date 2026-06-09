import React from 'react';
import { View } from 'react-native';

import { ScreenScrollView } from '../src/components/Screen';
import { AppText } from '../src/components/ui';
import { useTheme } from '../src/theme/ThemeProvider';

export default function TermsScreen() {
  const theme = useTheme();

  return (
    <ScreenScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
      <AppText variant="body" style={{ lineHeight: 22 }}>
        General information only. Rate and product figures are indicative; confirm all terms with the lender
        before applying. Nothing in this app is financial advice.
      </AppText>

      <AppText variant="h3" style={{ marginTop: 24, marginBottom: 8 }}>
        Data sources
      </AppText>
      <AppText variant="body" color="textMuted" style={{ lineHeight: 22 }}>
        Rate information is compiled from publicly available Australian banking product disclosures made
        available under applicable open data licences, including materials published under Australia&apos;s
        Consumer Data Right regime and the Consumer Data Standards maintained by the Data Standards Body
        (Treasury).
      </AppText>
      <AppText variant="body" color="textMuted" style={{ marginTop: 12, lineHeight: 22 }}>
        This application is not an accredited Consumer Data Right participant, does not use the CDR trade
        mark, and is not affiliated with the ACCC, OAIC, Treasury, or any data holder.
      </AppText>

      <View
        style={{
          marginTop: 24,
          padding: 12,
          borderRadius: theme.radius.md,
          backgroundColor: theme.colors.surface,
          borderWidth: 1,
          borderColor: theme.colors.border,
        }}
      >
        <AppText variant="tiny" color="textFaint" style={{ lineHeight: 18 }}>
          Australian Rates mobile app. Published rates refresh on a daily schedule when online; cached data
          remains available offline.
        </AppText>
      </View>
    </ScreenScrollView>
  );
}
