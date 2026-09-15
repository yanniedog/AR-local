export const CRASHLYTICS_ERROR_CATEGORIES: Readonly<Record<string, string>> = {
  app: 'app-lifecycle',
  global: 'unhandled-runtime',
  'app-update': 'app-update',
  payload: 'payload',
  store: 'data-store',
  'tracked-rates': 'tracked-rates',
  history: 'history',
  'bank-insights': 'bank-insights',
};

// Kept in lockstep with the protected diagnostics workflow. Every event that
// may enter private maintainer triage carries this exact, non-user identifier.
export const DIAGNOSTICS_PRIVACY_NOTICE_VERSION = '2026-09-03';
export const CRASHLYTICS_PRIVACY_NOTICE_KEY = 'ar_diagnostics_privacy_notice';

export const PRIVACY_RUNTIME_POLICY = Object.freeze({
  crashReportsRequireConsent: true,
  crashReportsUseFixedCategoriesOnly: true,
  appHealthAutomaticUpload: false,
  debugLogAutomaticUpload: false,
  sessionReplayCollected: false,
  lenderArtworkUsesVerifiedPayloadUrls: true,
  lenderArtworkRequestIncludesUserInputs: false,
  diagnosticsProcessor: 'Google Firebase Crashlytics',
  privateMaintainerTriageMayBeEnabled: true,
});

export const OPTIONAL_DIAGNOSTICS_TERMS =
  'Only after you opt in, Google Firebase Crashlytics can receive crash traces, device and app-build details, and fixed technical error categories. If private maintainer triage is enabled, an automatically redacted sample trace may also be copied to a private GitHub issue tracker that only maintainers can access and may be retained until that issue is closed or deleted. Automated redaction reduces, but cannot eliminate, the chance that a trace contains identifying details. Raw logs, searches, saved rates, profile and calculator inputs, routes, app-health results, and the Debug log remain on this device unless you explicitly share or upload a deidentified report. Session replay is not collected. You can disable crash reports in Settings at any time.';

export const LENDER_ARTWORK_TERMS =
  'When online, Australian Rates may load a lender logo from the public HTTPS address carried in the integrity-checked rates data. The image host receives ordinary connection metadata such as your IP address; the image request does not include your searches, saved rates, profile, or calculator inputs. During an app-health audit, and whenever artwork is unavailable, the app uses bundled artwork or a lender initial mark instead.';
