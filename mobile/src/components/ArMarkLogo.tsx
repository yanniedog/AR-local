import React from 'react';
import Svg, { Circle, Defs, LinearGradient, Path, Rect, Stop } from 'react-native-svg';

/** Dashboard shell mark (`site/assets/branding/ar-mark.svg` via Pi `/assets/branding/ar-mark.svg`). */
export function ArMarkLogo({ size = 36 }: { size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 96 96" accessibilityLabel="AustralianRates logo mark">
      <Defs>
        <LinearGradient id="arMarkBg" x1="10" y1="8" x2="86" y2="88" gradientUnits="userSpaceOnUse">
          <Stop offset="0" stopColor="#22d3ee" />
          <Stop offset="1" stopColor="#0ea5e9" />
        </LinearGradient>
      </Defs>
      <Rect x="6" y="6" width="84" height="84" rx="22" fill="#07111f" />
      <Rect x="8" y="8" width="80" height="80" rx="20" fill="url(#arMarkBg)" opacity={0.24} />
      <Path
        d="M16 48 48 22l32 26"
        fill="none"
        stroke="#e2f8ff"
        strokeWidth={7}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Path d="M24 68h48" fill="none" stroke="#e2f8ff" strokeWidth={6} strokeLinecap="round" />
      <Path
        d="m30 60 10-12 9 6 14-16"
        fill="none"
        stroke="#7dd3fc"
        strokeWidth={6}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Circle cx="63" cy="38" r="5" fill="#7dd3fc" />
    </Svg>
  );
}
