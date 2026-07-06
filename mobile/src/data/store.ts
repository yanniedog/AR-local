import AsyncStorage from '@react-native-async-storage/async-storage';
import * as BackgroundFetch from 'expo-background-fetch';
import * as TaskManager from 'expo-task-manager';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

import { DEFAULT_INTERESTS, normalizeInterests, resolveInterestSection } from './interests';
import { normalizeProfileFilters } from './profile';
import { normalizeCalcInputs } from './calc';
import { shouldWarmDetails } from './optionalPrefs';
import { BACKGROUND_TASK } from './notifications';
import { effectiveDeepSearch } from '../lib/proAccess';
import { bootstrapInitialState, createBootstrapActions } from './storeBootstrap';
import { createRefreshActions } from './storeRefresh';
import { createEnsureActions } from './storeEnsure';
import { createUserActions } from './storeUser';
import { DEFAULT_PREFS, type AppState } from './storeTypes';
import type { SectionKey } from '../types';

export { shouldWarmDetails } from './optionalPrefs';
export type { Prefs, Status } from './storeTypes';
export { DEFAULT_PREFS } from './storeTypes';

type StoreApi = {
  persist?: { rehydrate?: () => void | Promise<void> };
  getState: () => AppState;
};

const storeRef: { current: StoreApi | null } = { current: null };

export const useStore = create<AppState>()(
  persist(
    (set, get) => ({
      ...bootstrapInitialState,
      ...createBootstrapActions(set, get, () => storeRef.current!),
      ...createRefreshActions(set, get),
      ...createEnsureActions(set, get),
      ...createUserActions(set, get),
    }),
    {
      name: 'ar-rates',
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (s) => ({
        prefs: s.prefs,
        favorites: s.favorites,
        subscriptions: s.subscriptions,
        activeSection: s.activeSection,
      }),
      merge: (persisted, current) => {
        const p = persisted as Partial<AppState> | undefined;
        const prefs = {
          ...DEFAULT_PREFS,
          ...p?.prefs,
          interests: normalizeInterests(p?.prefs?.interests ?? DEFAULT_INTERESTS),
          profileFilters: normalizeProfileFilters(p?.prefs?.profileFilters),
          calc: normalizeCalcInputs(p?.prefs?.calc),
        };
        const persistedActiveSection = p?.activeSection;
        const isValidActiveSection =
          typeof persistedActiveSection === 'string' &&
          prefs.interests.includes(persistedActiveSection as SectionKey);
        const activeSection = isValidActiveSection
          ? (persistedActiveSection as SectionKey)
          : resolveInterestSection(prefs.interests, prefs.defaultSection);
        return {
          ...current,
          ...p,
          prefs,
          activeSection,
        };
      },
      onRehydrateStorage: () => () => {
        useStore.setState({ hydrated: true });
      },
    },
  ),
);

storeRef.current = useStore;

try {
  if (typeof TaskManager.isTaskDefined === 'function' && !TaskManager.isTaskDefined(BACKGROUND_TASK)) {
    TaskManager.defineTask(BACKGROUND_TASK, async () => {
      try {
        try {
          await useStore.persist?.rehydrate?.();
        } catch {
          // proceed with defaults if rehydrate fails
        }
        await useStore.getState().ensureCoreLoaded();
        const state = useStore.getState();
        if (shouldWarmDetails(state.prefs, state.subscriptions)) {
          await state.ensureDetails();
        }
        if (effectiveDeepSearch(state.prefs)) await state.ensureSearchIndex();
        const changed = await useStore.getState().refresh({});
        return changed
          ? BackgroundFetch.BackgroundFetchResult.NewData
          : BackgroundFetch.BackgroundFetchResult.NoData;
      } catch {
        return BackgroundFetch.BackgroundFetchResult.Failed;
      }
    });
  }
} catch {
  // TaskManager unavailable (e.g. web / test env) — background refresh is optional.
}
