import React from 'react';
import { View, type ViewStyle } from 'react-native';

import { useTheme } from '../theme/ThemeProvider';
import { ArMarkLogo } from './ArMarkLogo';
import { AppText } from './ui';

/** Header brand row aligned with dashboard `.site-brand` + `.site-brand-inline-logo`. */
export function BrandLockup({
  markSize = 36,
  style,
}: {
  markSize?: number;
  style?: ViewStyle;
}) {
  const theme = useTheme();
  return (
    <View style={[{ flexDirection: 'row', alignItems: 'center', gap: 10 }, style]}>
      <View
        style={{
          width: markSize,
          height: markSize,
          borderRadius: 9,
          borderWidth: 1,
          borderColor: theme.colors.border,
          backgroundColor: theme.colors.surface,
          alignItems: 'center',
          justifyContent: 'center',
          overflow: 'hidden',
        }}
      >
        <ArMarkLogo size={markSize - 4} />
      </View>
      <AppText variant="h3" weight="700" style={{ letterSpacing: -0.3 }}>
        AustralianRates
      </AppText>
    </View>
  );
}
