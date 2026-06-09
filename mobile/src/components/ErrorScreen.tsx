import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Pressable, Text, useColorScheme, View } from 'react-native';

import { DARK, LIGHT } from '../theme/colors';

/**
 * Self-contained error fallback used by the root ErrorBoundary. It deliberately
 * does NOT depend on ThemeProvider/store context, so it still renders correctly
 * even if a provider higher in the tree is what threw.
 */
export function ErrorScreen({ error, retry }: { error: Error; retry: () => void }) {
  const dark = useColorScheme() !== 'light';
  const colors = dark ? DARK : LIGHT;

  return (
    <View
      style={{
        flex: 1,
        backgroundColor: colors.bg,
        alignItems: 'center',
        justifyContent: 'center',
        padding: 28,
      }}
    >
      <View
        style={{
          backgroundColor: colors.card,
          borderRadius: 18,
          padding: 24,
          alignItems: 'center',
          maxWidth: 420,
          width: '100%',
        }}
      >
        <Ionicons name="warning-outline" size={40} color={colors.primary} />
        <Text style={{ color: colors.text, fontSize: 18, fontWeight: '800', marginTop: 12 }}>
          Something went wrong
        </Text>
        <Text
          style={{
            color: colors.textMuted,
            fontSize: 14,
            textAlign: 'center',
            marginTop: 8,
            lineHeight: 20,
          }}
        >
          The app hit an unexpected error. Your downloaded rates are safe — try again.
        </Text>
        <Text
          style={{ color: colors.textMuted, fontSize: 11, textAlign: 'center', marginTop: 10 }}
          numberOfLines={3}
        >
          {error?.message ?? String(error)}
        </Text>
        <Pressable
          onPress={retry}
          style={({ pressed }) => ({
            marginTop: 20,
            backgroundColor: colors.primary,
            paddingHorizontal: 22,
            paddingVertical: 12,
            borderRadius: 12,
            opacity: pressed ? 0.85 : 1,
          })}
        >
          <Text style={{ color: colors.onPrimary, fontWeight: '700', fontSize: 15 }}>Try again</Text>
        </Pressable>
      </View>
    </View>
  );
}
