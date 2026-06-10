import * as Haptics from 'expo-haptics';
import { Platform } from 'react-native';

async function run(fn: () => Promise<void>): Promise<void> {
  if (Platform.OS === 'web') return;
  try {
    await fn();
  } catch {
    // Haptics unavailable in some simulators / test environments.
  }
}

/** Toggle-style actions: favorite, compare mode, segment change. */
export function hapticSelection(): void {
  void run(() => Haptics.selectionAsync());
}

/** Confirmed actions: filter apply. */
export function hapticLightImpact(): void {
  void run(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light));
}

/** Manual refresh finished (success or up-to-date). */
export function hapticRefreshComplete(): void {
  void run(() => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success));
}
