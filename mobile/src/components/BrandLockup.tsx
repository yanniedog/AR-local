import { usePathname } from 'expo-router';
import React, { createContext, useContext, useEffect, useMemo, useRef } from 'react';
import { View, type StyleProp, type ViewStyle } from 'react-native';

import { useTheme } from '../theme/ThemeProvider';
import { ArMarkLogo } from './ArMarkLogo';
import { AppText } from './ui';

export type SplashMorphTarget = {
  x: number;
  y: number;
  width: number;
  height: number;
  markSize: number;
};

type SplashMorphContextValue = {
  registerTarget: (target: SplashMorphTarget) => void;
  morphComplete: boolean;
  setMorphComplete: (done: boolean) => void;
};

const SplashMorphContext = createContext<SplashMorphContextValue>({
  registerTarget: () => {},
  morphComplete: true,
  setMorphComplete: () => {},
});

export function SplashMorphProvider({
  children,
  morphComplete,
  setMorphComplete,
  registerTarget,
}: {
  children: React.ReactNode;
  morphComplete: boolean;
  setMorphComplete: (done: boolean) => void;
  registerTarget: (target: SplashMorphTarget) => void;
}) {
  const value = useMemo(
    () => ({ registerTarget, morphComplete, setMorphComplete }),
    [registerTarget, morphComplete, setMorphComplete],
  );

  return <SplashMorphContext.Provider value={value}>{children}</SplashMorphContext.Provider>;
}

export function useSplashMorph() {
  return useContext(SplashMorphContext);
}

function isHomeHeaderPath(pathname: string) {
  return pathname === '/(tabs)' || pathname === '/(tabs)/index' || pathname === '/';
}

/** Header brand row aligned with dashboard `.site-brand` + `.site-brand-inline-logo`. */
export function BrandLockup({
  markSize = 36,
  style,
}: {
  markSize?: number;
  style?: StyleProp<ViewStyle>;
}) {
  const theme = useTheme();
  const pathname = usePathname();
  const markRef = useRef<View>(null);
  const { registerTarget, morphComplete } = useSplashMorph();
  const isMorphTarget = isHomeHeaderPath(pathname) && markSize <= 28;

  useEffect(() => {
    if (!isMorphTarget || morphComplete) return;
    const measure = () => {
      markRef.current?.measureInWindow((x, y, width, height) => {
        if (width <= 0 || height <= 0) return;
        registerTarget({ x, y, width, height, markSize });
      });
    };
    const frame = requestAnimationFrame(measure);
    return () => cancelAnimationFrame(frame);
  }, [isMorphTarget, markSize, morphComplete, registerTarget, pathname]);

  return (
    <View style={[{ flexDirection: 'row', alignItems: 'center', gap: 10 }, style]}>
      <View
        ref={markRef}
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
          opacity: isMorphTarget && !morphComplete ? 0 : 1,
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
