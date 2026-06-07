import { Redirect } from 'expo-router';
import React from 'react';

import { useStore } from '../src/data/store';

export default function Index() {
  const hydrated = useStore((s) => s.hydrated);
  const onboarded = useStore((s) => s.prefs.onboarded);
  // Wait for persisted prefs to rehydrate before deciding, so returning users
  // aren't bounced to onboarding on a cold launch (AsyncStorage loads async).
  if (!hydrated) return null;
  return <Redirect href={onboarded ? '/(tabs)' : '/onboarding'} />;
}
