import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import React, { useEffect } from 'react';
import { View } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ErrorScreen } from '../src/components/ErrorScreen';
import { useStore } from '../src/data/store';
import { debugLog } from '../src/lib/debugLog';
import { initObservability, setDiagnosticsEnabled } from '../src/lib/observability';
import { ThemeProvider, useTheme } from '../src/theme/ThemeProvider';

SplashScreen.preventAutoHideAsync().catch(() => {});

// expo-router renders this when a child route throws during render.
export function ErrorBoundary({ error, retry }: { error: Error; retry: () => void }) {
  debugLog.error('app', `render error: ${error.message}`);
  return <ErrorScreen error={error} retry={retry} />;
}

function RootNavigator() {
  const theme = useTheme();
  const status = useStore((s) => s.status);
  const hydrated = useStore((s) => s.hydrated);
  const diagnosticsEnabled = useStore((s) => s.prefs.diagnosticsEnabled);
  const bootstrap = useStore((s) => s.bootstrap);

  useEffect(() => {
    void initObservability();
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    void setDiagnosticsEnabled(diagnosticsEnabled);
  }, [hydrated, diagnosticsEnabled]);

  useEffect(() => {
    void debugLog.restoreFromStorage().then(() => {
      debugLog.info('app', 'bootstrap starting');
      void bootstrap();
    });
  }, [bootstrap]);

  useEffect(() => {
    // Hold the splash until prefs have rehydrated AND data is ready, so the first
    // frame is the correct route with the correct theme (no onboarding flash).
    if (hydrated && (status === 'ready' || status === 'error')) {
      SplashScreen.hideAsync().catch(() => {});
    }
  }, [status, hydrated]);

  return (
    <View style={{ flex: 1, backgroundColor: theme.colors.bg }}>
      <StatusBar style={theme.dark ? 'light' : 'dark'} />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: theme.colors.surface },
          headerTitleStyle: { color: theme.colors.text },
          headerTintColor: theme.colors.primary,
          headerShadowVisible: false,
          contentStyle: { backgroundColor: theme.colors.bg },
        }}
      >
        <Stack.Screen name="index" options={{ headerShown: false }} />
        <Stack.Screen name="onboarding" options={{ headerShown: false }} />
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="node" options={{ title: 'Browse' }} />
        <Stack.Screen name="search" options={{ title: 'Search' }} />
        <Stack.Screen name="product/[key]" options={{ title: 'Product', headerBackTitle: 'Back' }} />
        <Stack.Screen name="bank/[provider]" options={{ title: 'Lender' }} />
        <Stack.Screen name="banks" options={{ title: 'Lenders' }} />
        <Stack.Screen name="compare" options={{ title: 'Compare', presentation: 'modal' }} />
        <Stack.Screen name="debug-log" options={{ title: 'Debug log', headerBackTitle: 'Settings' }} />
      </Stack>
    </View>
  );
}

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <ThemeProvider>
          <RootNavigator />
        </ThemeProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
