import * as Notifications from 'expo-notifications';
import { Stack, router, type Href } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import React, { useEffect, useRef } from 'react';
import { View } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ErrorScreen } from '../src/components/ErrorScreen';
import { routeFromNotificationResponse } from '../src/data/notifications';
import { useStore } from '../src/data/store';
import { debugLog, installGlobalErrorHandlers } from '../src/lib/debugLog';
import { setDiagnosticsEnabled } from '../src/lib/observability';
import { ThemeProvider, useTheme } from '../src/theme/ThemeProvider';

SplashScreen.preventAutoHideAsync().catch(() => {});

// expo-router renders this when a child route throws during render.
export function ErrorBoundary({ error, retry }: { error: Error; retry: () => void }) {
  debugLog.error('app', `render error: ${error.message}`);
  return <ErrorScreen error={error} retry={retry} />;
}

function navigateFromNotification(href: Href): void {
  debugLog.info('notify', `tap route ${String(href)}`);
  router.push(href);
}

function RootNavigator() {
  const theme = useTheme();
  const status = useStore((s) => s.status);
  const hydrated = useStore((s) => s.hydrated);
  const diagnosticsEnabled = useStore((s) => s.prefs.diagnosticsEnabled);
  const bootstrap = useStore((s) => s.bootstrap);
  const pendingNotificationRoute = useRef<Href | null>(null);
  const coldStartChecked = useRef(false);

  useEffect(() => {
    if (!hydrated) return;
    void setDiagnosticsEnabled(diagnosticsEnabled);
  }, [hydrated, diagnosticsEnabled]);

  useEffect(() => {
    installGlobalErrorHandlers();
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

  useEffect(() => {
    const queueRoute = (href: Href | null) => {
      if (!href) return;
      if (hydrated && (status === 'ready' || status === 'error')) {
        navigateFromNotification(href);
        return;
      }
      pendingNotificationRoute.current = href;
    };

    const sub = Notifications.addNotificationResponseReceivedListener((response) => {
      queueRoute(routeFromNotificationResponse(response));
    });

    if (!coldStartChecked.current) {
      coldStartChecked.current = true;
      void Notifications.getLastNotificationResponseAsync().then((response) => {
        queueRoute(routeFromNotificationResponse(response));
      });
    }

    return () => sub.remove();
  }, [hydrated, status]);

  useEffect(() => {
    if (!hydrated || (status !== 'ready' && status !== 'error')) return;
    const href = pendingNotificationRoute.current;
    if (!href) return;
    pendingNotificationRoute.current = null;
    navigateFromNotification(href);
  }, [hydrated, status]);

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
        <Stack.Screen name="hierarchy" options={{ title: 'Browse tree' }} />
        <Stack.Screen name="search" options={{ title: 'Search' }} />
        <Stack.Screen name="product/[key]" options={{ title: 'Product', headerBackTitle: 'Back' }} />
        <Stack.Screen name="bank/[provider]" options={{ title: 'Lender' }} />
        <Stack.Screen name="banks" options={{ title: 'Lenders' }} />
        <Stack.Screen name="compare" options={{ title: 'Compare', presentation: 'modal' }} />
        <Stack.Screen name="debug-log" options={{ title: 'Debug log', headerBackTitle: 'Settings' }} />
        <Stack.Screen name="terms" options={{ title: 'Terms', headerBackTitle: 'Settings' }} />
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
