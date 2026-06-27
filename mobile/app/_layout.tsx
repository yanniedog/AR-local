import {
  MaterialSymbols_400Regular,
} from '@expo-google-fonts/material-symbols';
import {
  MaterialSymbolsOutlined_400Regular,
  useFonts,
} from '@expo-google-fonts/material-symbols-outlined';
import * as Notifications from 'expo-notifications';
import { Stack, router, type Href } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Platform, StyleSheet, useWindowDimensions, View } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import Animated, {
  Easing,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AppLockGate } from '../src/components/AppLockGate';
import { ArMarkLogo } from '../src/components/ArMarkLogo';
import { SplashMorphProvider, type SplashMorphTarget } from '../src/components/BrandLockup';
import { DataUnavailableScreen } from '../src/components/DataUnavailableScreen';
import { ErrorScreen } from '../src/components/ErrorScreen';
import { AppText } from '../src/components/ui';
import { routeFromNotificationResponse } from '../src/data/notifications';
import { useStore } from '../src/data/store';
import { androidStackScreenOptions } from '../src/lib/androidChrome';
import { subscribeAuth } from '../src/lib/auth';
import { syncContentKeys } from '../src/lib/keyService';
import { debugLog, installGlobalErrorHandlers } from '../src/lib/debugLog';
import { logSwallowedError } from '../src/lib/degradationLog';
import { setDiagnosticsEnabled } from '../src/lib/observability';
import { ThemeProvider, useTheme } from '../src/theme/ThemeProvider';

SplashScreen.preventAutoHideAsync().catch((err) => logSwallowedError('splash.preventAutoHide', err));

const SPLASH_MARK = 88;
const MORPH_MS = 680;
const FADE_MS = 320;

export function ErrorBoundary({ error, retry }: { error: Error; retry: () => void }) {
  debugLog.error('app', `render error: ${error.message}`);
  return <ErrorScreen error={error} retry={retry} />;
}

function navigateFromNotification(href: Href): void {
  debugLog.info('notify', `tap route ${String(href)}`);
  router.push(href);
}

function BrandedSplashOverlay({
  visible,
  morphTarget,
  onboarded,
  onMorphComplete,
}: {
  visible: boolean;
  morphTarget: SplashMorphTarget | null;
  onboarded: boolean;
  onMorphComplete: () => void;
}) {
  const theme = useTheme();
  const { width: screenW, height: screenH } = useWindowDimensions();
  const progress = useSharedValue(0);
  const overlayOpacity = useSharedValue(1);
  const [morphWaitExpired, setMorphWaitExpired] = useState(false);

  const finish = useCallback(() => {
    onMorphComplete();
  }, [onMorphComplete]);

  useEffect(() => {
    if (!visible) return;
    progress.value = 0;
    overlayOpacity.value = 1;
    setMorphWaitExpired(false);
  }, [visible, overlayOpacity, progress]);

  useEffect(() => {
    if (!visible || !onboarded || morphTarget) return;
    const timer = setTimeout(() => setMorphWaitExpired(true), 450);
    return () => clearTimeout(timer);
  }, [visible, onboarded, morphTarget]);

  useEffect(() => {
    if (!visible) return;
    const canMorph = onboarded && morphTarget != null;
    const shouldFade = !onboarded || morphWaitExpired;
    if (!canMorph && !shouldFade) return;

    if (canMorph) {
      progress.value = withTiming(1, { duration: MORPH_MS, easing: Easing.out(Easing.cubic) }, (done) => {
        if (done) {
          overlayOpacity.value = withTiming(0, { duration: 120 }, (faded) => {
            if (faded) runOnJS(finish)();
          });
        }
      });
      return;
    }
    overlayOpacity.value = withTiming(0, { duration: FADE_MS }, (done) => {
      if (done) runOnJS(finish)();
    });
  }, [visible, onboarded, morphTarget, morphWaitExpired, finish, overlayOpacity, progress]);

  const startX = screenW / 2 - SPLASH_MARK / 2;
  const startY = screenH / 2 - SPLASH_MARK / 2 - 28;
  const endScale = morphTarget ? morphTarget.markSize / SPLASH_MARK : 1;

  const markStyle = useAnimatedStyle(() => {
    if (!morphTarget || !onboarded) {
      return {
        opacity: overlayOpacity.value,
        transform: [{ translateX: startX }, { translateY: startY }],
      };
    }
    const t = progress.value;
    return {
      opacity: overlayOpacity.value,
      transform: [
        { translateX: startX + (morphTarget.x - startX) * t },
        { translateY: startY + (morphTarget.y - startY) * t },
        { scale: 1 + (endScale - 1) * t },
      ],
    };
  }, [morphTarget, onboarded, startX, startY, endScale]);

  const titleStyle = useAnimatedStyle(() => ({
    opacity: overlayOpacity.value * (1 - progress.value),
    transform: [{ translateY: progress.value * 12 }],
  }));

  const shellStyle = useAnimatedStyle(() => ({
    opacity: overlayOpacity.value,
  }));

  if (!visible) return null;

  return (
    <Animated.View
      pointerEvents="none"
      style={[
        StyleSheet.absoluteFillObject,
        { backgroundColor: theme.colors.bg, zIndex: 100, alignItems: 'center', justifyContent: 'center' },
        shellStyle,
      ]}
    >
      <Animated.View
        style={[
          {
            position: 'absolute',
            left: 0,
            top: 0,
            width: SPLASH_MARK,
            height: SPLASH_MARK,
            borderRadius: 12,
            borderWidth: 1,
            borderColor: theme.colors.border,
            backgroundColor: theme.colors.surface,
            alignItems: 'center',
            justifyContent: 'center',
            overflow: 'hidden',
          },
          markStyle,
        ]}
      >
        <ArMarkLogo size={SPLASH_MARK - 8} />
      </Animated.View>
      <Animated.View style={[{ position: 'absolute', top: screenH / 2 + SPLASH_MARK / 2 - 4 }, titleStyle]}>
        <AppText variant="h2" weight="700" style={{ letterSpacing: -0.3 }}>
          AustralianRates
        </AppText>
      </Animated.View>
    </Animated.View>
  );
}

function RootNavigator() {
  const theme = useTheme();
  const status = useStore((s) => s.status);
  const hydrated = useStore((s) => s.hydrated);
  const onboarded = useStore((s) => s.prefs.onboarded);
  const dataUnavailable = hydrated && status === 'error';
  const diagnosticsEnabled = useStore((s) => s.prefs.diagnosticsEnabled);
  const bootstrap = useStore((s) => s.bootstrap);
  const androidHeader = androidStackScreenOptions(theme);
  const pendingNotificationRoute = useRef<Href | null>(null);
  const coldStartChecked = useRef(false);
  const [morphComplete, setMorphComplete] = useState(false);
  const [overlayVisible, setOverlayVisible] = useState(true);
  const [morphTarget, setMorphTarget] = useState<SplashMorphTarget | null>(null);

  const appReady = hydrated && (status === 'ready' || status === 'error');

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

  // Refresh tier-issued content keys on app start / sign-in (Phase D; no-op
  // until the key service URL is configured).
  useEffect(() => subscribeAuth((user) => {
    if (user) void syncContentKeys();
  }), []);

  useEffect(() => {
    if (!appReady) return;
    SplashScreen.hideAsync().catch((err) => logSwallowedError('splash.hide', err));
  }, [appReady]);

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

  const registerTarget = useCallback((target: SplashMorphTarget) => {
    setMorphTarget((prev) => prev ?? target);
  }, []);

  const handleMorphComplete = useCallback(() => {
    setMorphComplete(true);
    setOverlayVisible(false);
  }, []);

  if (dataUnavailable) {
    return (
      <View style={{ flex: 1, backgroundColor: theme.colors.bg }}>
        <StatusBar style={theme.dark ? 'light' : 'dark'} />
        <DataUnavailableScreen />
      </View>
    );
  }

  return (
    <SplashMorphProvider
      morphComplete={morphComplete}
      setMorphComplete={setMorphComplete}
      registerTarget={registerTarget}
    >
      <View style={{ flex: 1, backgroundColor: theme.colors.bg }}>
        <StatusBar style={theme.dark ? 'light' : 'dark'} />
        <Stack
          screenOptions={{
            headerStyle: { backgroundColor: theme.colors.surface },
            headerTitleStyle: { color: theme.colors.text },
            headerTintColor: theme.colors.primary,
            headerShadowVisible: false,
            contentStyle: { backgroundColor: theme.colors.bg },
            ...androidHeader,
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
          <Stack.Screen name="calculator" options={{ title: 'Switch & save' }} />
          <Stack.Screen name="rba" options={{ title: 'Why rates move' }} />
          <Stack.Screen name="profile" options={{ title: 'Your profile' }} />
          <Stack.Screen name="debug-log" options={{ title: 'Debug log', headerBackTitle: 'Settings' }} />
          <Stack.Screen name="terms" options={{ title: 'Terms', headerBackTitle: 'Settings' }} />
        </Stack>
        {appReady ? (
          <BrandedSplashOverlay
            visible={overlayVisible}
            morphTarget={morphTarget}
            onboarded={onboarded}
            onMorphComplete={handleMorphComplete}
          />
        ) : null}
      </View>
    </SplashMorphProvider>
  );
}

export default function RootLayout() {
  const [fontsLoaded] = useFonts({
    MaterialSymbolsOutlined_400Regular,
    MaterialSymbols_400Regular,
  });

  if (Platform.OS === 'android' && !fontsLoaded) {
    return null;
  }

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <ThemeProvider>
          <AppLockGate>
            <RootNavigator />
          </AppLockGate>
        </ThemeProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
