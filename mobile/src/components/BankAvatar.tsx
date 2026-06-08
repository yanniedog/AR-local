import React, { useEffect, useState } from 'react';
import { Image, Text, View } from 'react-native';

import { useStore } from '../data/store';

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
  const brand = useStore((s) => s.core?.brands?.[provider]);
  const [logoFailed, setLogoFailed] = useState(false);
  const color = brand?.color ?? '#3a4254';
  const short = (brand?.short ?? provider.slice(0, 2)).toUpperCase().slice(0, 5);
  const fontSize = short.length <= 3 ? size * 0.34 : size * 0.26;
  const logo = brand?.logo;

  useEffect(() => setLogoFailed(false), [logo]);

  if (logo && !logoFailed) {
    return (
      <View
        style={{
          width: size,
          height: size,
          alignItems: 'center',
          justifyContent: 'center',
        }}
        accessibilityLabel={provider}
      >
        <Image
          source={{ uri: logo }}
          resizeMode="contain"
          style={{ width: size * 0.88, height: size * 0.88 }}
          onError={() => setLogoFailed(true)}
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
      accessibilityLabel={provider}
    >
      <Text style={{ color: contrastText(color), fontWeight: '800', fontSize }}>{short}</Text>
    </View>
  );
}
