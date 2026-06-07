import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Pressable, Text, useColorScheme, View } from 'react-native';

/**
 * Self-contained error fallback used by the root ErrorBoundary. It deliberately
 * does NOT depend on ThemeProvider/store context, so it still renders correctly
 * even if a provider higher in the tree is what threw.
 */
export function ErrorScreen({ error, retry }: { error: Error; retry: () => void }) {
  const dark = useColorScheme() !== 'light';
  const bg = dark ? '#0b0f17' : '#f4f6fb';
  const card = dark ? '#161d2e' : '#ffffff';
  const text = dark ? '#e6edf7' : '#0b1220';
  const muted = dark ? '#9aa7bd' : '#5b6678';
  const primary = dark ? '#4d8dff' : '#1f6feb';

  return (
    <View style={{ flex: 1, backgroundColor: bg, alignItems: 'center', justifyContent: 'center', padding: 28 }}>
      <View
        style={{
          backgroundColor: card,
          borderRadius: 18,
          padding: 24,
          alignItems: 'center',
          maxWidth: 420,
          width: '100%',
        }}
      >
        <Ionicons name="warning-outline" size={40} color={primary} />
        <Text style={{ color: text, fontSize: 18, fontWeight: '800', marginTop: 12 }}>Something went wrong</Text>
        <Text style={{ color: muted, fontSize: 14, textAlign: 'center', marginTop: 8, lineHeight: 20 }}>
          The app hit an unexpected error. Your downloaded rates are safe — try again.
        </Text>
        <Text style={{ color: muted, fontSize: 11, textAlign: 'center', marginTop: 10 }} numberOfLines={3}>
          {error?.message ?? String(error)}
        </Text>
        <Pressable
          onPress={retry}
          style={({ pressed }) => ({
            marginTop: 20,
            backgroundColor: primary,
            paddingHorizontal: 22,
            paddingVertical: 12,
            borderRadius: 12,
            opacity: pressed ? 0.85 : 1,
          })}
        >
          <Text style={{ color: '#fff', fontWeight: '700', fontSize: 15 }}>Try again</Text>
        </Pressable>
      </View>
    </View>
  );
}
