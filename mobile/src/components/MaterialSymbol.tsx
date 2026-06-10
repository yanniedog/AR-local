import React from 'react';
import { Platform, Text, type TextStyle } from 'react-native';

type Props = {
  name: string;
  size?: number;
  color?: string;
  /** Filled variant for active navigation states (Android M3). */
  filled?: boolean;
  style?: TextStyle;
};

const OUTLINED = 'MaterialSymbolsOutlined_400Regular';
const FILLED = 'MaterialSymbols_400Regular';

/** Renders a Material Symbols icon via font ligatures (Android M3 chrome). */
export function MaterialSymbol({ name, size = 24, color, filled = false, style }: Props) {
  if (Platform.OS !== 'android') return null;

  return (
    <Text
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[
        {
          fontFamily: filled ? FILLED : OUTLINED,
          fontSize: size,
          color,
          lineHeight: size,
          includeFontPadding: false,
          textAlignVertical: 'center',
        },
        style,
      ]}
    >
      {name}
    </Text>
  );
}
