import { RATE_MOVE_BPS_THRESHOLD } from '../config';
import type {
  CorePayload,
  DetailsPayload,
  Manifest,
  PayloadSource,
  ProductDetail,
  RateRow,
  SectionKey,
} from '../types';
import type { PayloadProgressSnapshot } from './downloadProgress';
import type { FilterSnapshot, Subscription } from './subscriptions';
import type { SearchIndexPayload } from './detailSearch';
import type { BankInsightsPayload } from './bankInsights';
import type { RbaCalendar } from './rbaCalendar';
import type { HistoryBanksPayload } from './historyPayload';
import type { ProductHistoryPayload } from './productHistory';
import { DEFAULT_INTERESTS } from './interests';
import { EMPTY_PROFILE, type ProfileFilters } from './profile';
import { EMPTY_CALC, type CalcInputs } from './calc';
import type { ThemeMode } from '../theme/theme';
import type { RefreshOutcomeKind } from '../components/bannerState';

export interface Prefs {
  themeMode: ThemeMode;
  defaultSection: SectionKey;
  notificationsEnabled: boolean;
  /** Session replay (Clarity) + crash/log reporting (Firebase Crashlytics). */
  diagnosticsEnabled: boolean;
  wifiOnly: boolean;
  includeNonStandard: boolean;
  /** How savings & term-deposit lists rank: 'base' ongoing rate (default, honest)
   *  vs 'max' headline/bonus rate. Mirrors RankMetric in data/selectors. */
  depositRankMetric: 'base' | 'max';
  /** Fulltext search across product info (off by default). */
  enableDeepSearch: boolean;
  /** Section ribbon time-series chart in Charts & trends (off by default). */
  showHistoryRibbon: boolean;
  /** Rate Intelligence Pro — local stub until store IAP is wired. */
  rateIntelligencePro: boolean;
  onboarded: boolean;
  interests: SectionKey[];
  rateMoveThresholdBps: number;
  /** APK build_number whose update banner the user dismissed (null = none). */
  dismissedUpdateBuild: string | null;
  /** Require fingerprint/Face ID (with device-credential fallback) on app start. */
  appLockEnabled: boolean;
  /** Saved product profile — default filters applied across the app. */
  profileFilters: ProfileFilters;
  /** Persisted mortgage/savings calculator inputs (so the calc remembers your situation). */
  calc: CalcInputs;
}

export const DEFAULT_PREFS: Prefs = {
  themeMode: 'system',
  defaultSection: 'Mortgage',
  notificationsEnabled: false,
  diagnosticsEnabled: true,
  wifiOnly: false,
  includeNonStandard: false,
  depositRankMetric: 'base',
  enableDeepSearch: false,
  showHistoryRibbon: false,
  rateIntelligencePro: false,
  onboarded: false,
  interests: [...DEFAULT_INTERESTS],
  rateMoveThresholdBps: RATE_MOVE_BPS_THRESHOLD,
  dismissedUpdateBuild: null,
  appLockEnabled: false,
  profileFilters: { ...EMPTY_PROFILE },
  calc: { ...EMPTY_CALC },
};

export type Status = 'idle' | 'loading' | 'ready' | 'error';

export interface AppState {
  status: Status;
  refreshing: boolean;
  source: PayloadSource;
  manifest: Manifest | null;
  core: CorePayload | null;
  details: DetailsPayload | null;
  searchIndex: SearchIndexPayload | null;
  historyBanks: HistoryBanksPayload | null;
  /** Set when optional history payload download/parse fails (pref may stay on). */
  historyBanksError: string | null;
  /** Per-bank history + rate-move events (Pro bank intelligence). */
  bankInsights: BankInsightsPayload | null;
  bankInsightsError: string | null;
  /** RBA decision calendar + forward schedule for the countdown (in-memory only). */
  rbaCalendar: RbaCalendar | null;
  rbaCalendarSha: string | null;
  rbaCalendarError: string | null;
  /** Per-product representative rate over time (derived on-device from dated cores). */
  productHistory: ProductHistoryPayload | null;
  productHistoryError: string | null;
  detailsLoading: boolean;
  error: string | null;
  offline: boolean;
  lastCheckedAt: string | null;
  /** Live payload fetch metrics while upgrading from bundled sample. */
  payloadProgress: PayloadProgressSnapshot | null;
  /** Transient snackbar after refresh completes (success / failure / Wi-Fi skip). */
  refreshOutcome: RefreshOutcomeKind | null;
  /** True once persisted prefs/favorites have rehydrated from AsyncStorage. */
  hydrated: boolean;
  /** Last-selected product section; synced across Home and Browse. */
  activeSection: SectionKey;

  prefs: Prefs;
  favorites: string[];
  subscriptions: Subscription[];

  bootstrap: () => Promise<void>;
  retryDataLoad: () => Promise<void>;
  loadSampleFallback: () => Promise<void>;
  /** Load core/manifest from disk cache if not already in memory (used by the headless task). */
  ensureCoreLoaded: () => Promise<void>;
  refresh: (opts?: { force?: boolean; manual?: boolean }) => Promise<boolean>;
  ensureDetails: (opts?: { forProductView?: boolean }) => Promise<void>;
  ensureSearchIndex: () => Promise<void>;
  ensureHistoryBanks: (opts?: { force?: boolean }) => Promise<void>;
  ensureBankInsights: (opts?: { force?: boolean }) => Promise<void>;
  ensureRbaCalendar: () => Promise<void>;
  ensureProductHistory: (opts?: { force?: boolean }) => Promise<void>;
  retryHistoryBanks: () => Promise<void>;
  retryBankInsights: () => Promise<void>;
  getDetail: (productKey: string) => ProductDetail | null;
  toggleFavorite: (key: string) => void;
  isFavorite: (key: string) => boolean;
  subscribeProduct: (productKey: string, rateIndex: number | null, labelRow: RateRow) => boolean;
  unsubscribeProduct: (productKey: string, rateIndex: number | null) => void;
  subscribeSearch: (input: {
    section: SectionKey;
    path: string[];
    hierarchyScoped: boolean;
    query: string;
    filters: FilterSnapshot;
  }) => boolean;
  unsubscribeSearch: (id: string) => void;
  removeSubscription: (id: string) => void;
  restoreSubscription: (sub: Subscription) => void;
  isProductSubscribed: (productKey: string, rateIndex: number | null) => boolean;
  findSearchSubscription: (input: {
    section: SectionKey;
    path: string[];
    hierarchyScoped: boolean;
    query: string;
    filters: FilterSnapshot;
  }) => Subscription | undefined;
  setPref: <K extends keyof Prefs>(key: K, value: Prefs[K]) => void;
  setActiveSection: (section: SectionKey) => void;
  completeOnboarding: (interests: SectionKey[], notifications: boolean) => void;
  clearCache: () => Promise<void>;
  clearRefreshOutcome: () => void;
}

export type StoreSet = (
  partial: Partial<AppState> | ((state: AppState) => Partial<AppState>),
) => void;
export type StoreGet = () => AppState;
