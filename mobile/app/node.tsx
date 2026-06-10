import { Redirect, useLocalSearchParams } from 'expo-router';
import React from 'react';

import { SECTIONS, SECTION_ORDER } from '../src/constants';
import type { SectionKey } from '../src/types';

/** Legacy /node deep links redirect into the Browse tab drill-down. */
export default function NodeScreen() {
  const { section: secRaw, path: pathRaw } = useLocalSearchParams<{ section: string; path?: string }>();
  const section = (SECTION_ORDER.includes(secRaw as SectionKey) ? secRaw : 'Mortgage') as SectionKey;
  const path = pathRaw ?? '';

  return (
    <Redirect
      href={{
        pathname: '/browse',
        params: {
          section: SECTIONS[section].slug,
          ...(path ? { path } : {}),
        },
      }}
    />
  );
}
