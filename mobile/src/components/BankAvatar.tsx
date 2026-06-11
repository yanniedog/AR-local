import React, { useMemo, useState } from 'react';
import { Image, Text, View } from 'react-native';

import { resolveBankLogoSources, resolveBrandShort } from '../data/bankBrand';
import { useStore } from '../data/store';
import { useTheme } from '../theme/ThemeProvider';

function contrastText(hex: string): string {
  const c = hex.replace('#', '');
  if (c.length < 6) return '#ffffff';
  const r = parseInt(c.slice(0, 2), 16);
  const g = parseInt(c.slice(2, 4), 16);
  const b = parseInt(c.slice(4, 6), 16);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.6 ? '#0b1220' : '#ffffff';
}

export function BankAvatar({ provider, size = 42 }: { provider: string; size?: number }) {
  const theme = useTheme();
  const brand = useStore((s) => s.core?.brands?.[provider]);
  const sources = useMemo(
    () => resolveBankLogoSources(provider, brand?.logo, brand?.logo_uri),
    [provider, brand?.logo, brand?.logo_uri],
  );
  const [prevSources, setPrevSources] = useState(sources);
  const [sourceIdx, setSourceIdx] = useState(0);
  const [exhausted, setExhausted] = useState(false);

  if (sources !== prevSources) {
    setPrevSources(sources);
    setSourceIdx(0);
    setExhausted(false);
  }

  const color = brand?.color ?? theme.colors.chipText;
  const short = resolveBrandShort(provider, brand?.short).toUpperCase().slice(0, 5);
  const fontSize = short.length <= 3 ? size * 0.34 : size * 0.26;
  const activeSource = sources[sourceIdx];

  if (activeSource != null && !exhausted) {
    return (
      <View
        style={{
          width: size,
          height: size,
          alignItems: 'center',
          justifyContent: 'center',
        }}
        accessible
        accessibilityLabel={provider}
      >
        <Image
          accessible={false}
          source={typeof activeSource === 'number' ? activeSource : { uri: activeSource }}
          resizeMode="contain"
          style={{ width: size * 0.88, height: size * 0.88 }}
          onError={() => {
            if (sourceIdx + 1 < sources.length) setSourceIdx((idx) => idx + 1);
            else setExhausted(true);
          }}
        />
      </View>
    );
  }

  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: size / 4,
        backgroundColor: color,
        alignItems: 'center',
        justifyContent: 'center',
      }}
      accessible
      accessibilityLabel={provider}
    >
      <Text accessible={false} style={{ color: contrastText(color), fontWeight: '800', fontSize }}>
        {short}
      </Text>
    </View>
  );
}
