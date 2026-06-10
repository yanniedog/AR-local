import React from 'react';
import {
  Pressable,
  type PressableProps,
  type PressableStateCallbackType,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

/** Material / WCAG 2.5.5 minimum touch target (dp). */
export const TOUCH_TARGET_MIN = 48;

export const DEFAULT_HIT_SLOP = { top: 8, bottom: 8, left: 8, right: 8 };

export type TouchTargetProps = PressableProps & {
  /** Also enforce minWidth (icon buttons, square controls). */
  square?: boolean;
  /** Stretch to fill parent width (settings rows, list actions). */
  fill?: boolean;
};

export function TouchTarget({
  children,
  style,
  hitSlop = DEFAULT_HIT_SLOP,
  square = false,
  fill = false,
  ...rest
}: TouchTargetProps) {
  const base: ViewStyle = {
    minHeight: TOUCH_TARGET_MIN,
    justifyContent: 'center',
    alignItems: 'center',
  };
  if (square) {
    base.minWidth = TOUCH_TARGET_MIN;
  }
  if (fill) {
    base.alignSelf = 'stretch';
    base.width = '100%';
  }

  const resolveStyle = (
    state: PressableStateCallbackType,
  ): StyleProp<ViewStyle> => {
    const resolved = typeof style === 'function' ? style(state) : style;
    return [base, resolved];
  };

  return (
    <Pressable hitSlop={hitSlop} style={resolveStyle} {...rest}>
      {children}
    </Pressable>
  );
}
