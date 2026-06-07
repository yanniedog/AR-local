import { Redirect } from 'expo-router';
import React from 'react';

import { useStore } from '../src/data/store';

export default function Index() {
  const onboarded = useStore((s) => s.prefs.onboarded);
  return <Redirect href={onboarded ? '/(tabs)' : '/onboarding'} />;
}
