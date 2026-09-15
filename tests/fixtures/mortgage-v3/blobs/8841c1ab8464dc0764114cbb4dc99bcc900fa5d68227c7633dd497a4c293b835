/** Live payload transfer / processing snapshot (real metrics only). */
export type PayloadProgressPhase =
  | 'manifest'
  | 'finalize'
  | 'download'
  | 'verify'
  | 'inflate'
  | 'parse'
  | 'install';

export const PAYLOAD_PROGRESS_PHASES: PayloadProgressPhase[] = [
  'manifest',
  'finalize',
  'download',
  'verify',
  'inflate',
  'parse',
  'install',
];

/** Inclusive phase band on the overall 0–100 determinate bar. */
const PHASE_BANDS: Record<PayloadProgressPhase, readonly [number, number]> = {
  manifest: [0, 6],
  finalize: [6, 12],
  download: [12, 78],
  verify: [78, 84],
  inflate: [84, 90],
  parse: [90, 96],
  install: [96, 100],
};

export interface PayloadProgressSnapshot {
  phase: PayloadProgressPhase;
  fileName: string;
  bytesReceived: number;
  totalBytes: number | null;
  /** Epoch ms when the current transfer step started (for rate / ETA). */
  startedAt: number;
  /**
   * When false, CPU-bound work is still running inside this phase — never fill
   * to the phase ceiling (avoids a false 100% while JSON.parse / inflate runs).
   * Transfer phases omit this and use byte progress alone.
   */
  phaseComplete?: boolean;
}

export type PayloadProgressHandler = (snapshot: PayloadProgressSnapshot) => void;

export interface PayloadProgressViewModel {
  /** Overall 0–100 determinate fill for the sync bar. */
  overallPercent: number;
  phaseText: string;
  detailLine: string;
  etaText: string;
  rateText: string;
  fileName: string;
  /** True when the bar should use a native soft-motion fill (JS may be blocked). */
  softMotion: boolean;
}

export function fileNameFromUrl(url: string): string {
  try {
    const path = new URL(url).pathname;
    const base = path.split('/').pop();
    return base ? decodeURIComponent(base) : url;
  } catch {
    const fallbackBase = url.split('/').pop();
    return fallbackBase || url;
  }
}

/** Smoothed bytes/sec from elapsed wall time since `startedAt`. */
export function computeTransferRate(
  bytesReceived: number,
  startedAt: number,
  now: number = Date.now(),
): number {
  const elapsedSec = (now - startedAt) / 1000;
  if (elapsedSec <= 0 || bytesReceived <= 0) return 0;
  return bytesReceived / elapsedSec;
}

export function formatTransferRate(bytesPerSec: number): string {
  if (!Number.isFinite(bytesPerSec) || bytesPerSec <= 0) return '—';
  if (bytesPerSec >= 1024 * 1024) return `${(bytesPerSec / (1024 * 1024)).toFixed(1)} MB/s`;
  if (bytesPerSec >= 1024) return `${(bytesPerSec / 1024).toFixed(1)} KB/s`;
  return `${Math.round(bytesPerSec)} B/s`;
}

export function computePercent(bytesReceived: number, totalBytes: number | null): number | null {
  if (totalBytes == null || totalBytes <= 0) return null;
  return Math.min(100, Math.round((bytesReceived / totalBytes) * 100));
}

export function computeEtaSeconds(
  bytesReceived: number,
  totalBytes: number | null,
  bytesPerSec: number,
): number | null {
  if (totalBytes == null || totalBytes <= bytesReceived || bytesPerSec <= 0) return null;
  return (totalBytes - bytesReceived) / bytesPerSec;
}

export function formatEta(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '—';
  if (seconds < 1) return '<1s';
  const s = Math.ceil(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem ? `${m}m ${rem}s` : `${m}m`;
}

export function phaseLabel(phase: PayloadProgressPhase): string {
  switch (phase) {
    case 'manifest':
      return 'Fetching catalog';
    case 'finalize':
      return 'Checking ingest status';
    case 'download':
      return 'Downloading rates';
    case 'verify':
      return 'Verifying checksum';
    case 'inflate':
      return 'Decompressing';
    case 'parse':
      return 'Parsing rates';
    case 'install':
      return 'Saving rates';
  }
}

function isTransferPhase(phase: PayloadProgressPhase): boolean {
  return phase === 'manifest' || phase === 'download';
}

function lerpBand(
  band: readonly [number, number],
  bytesReceived: number,
  totalBytes: number | null,
): number {
  const [lo, hi] = band;
  const inner = computePercent(bytesReceived, totalBytes);
  if (inner == null) return lo + (hi - lo) * 0.35;
  return lo + (inner / 100) * (hi - lo);
}

/**
 * Soft fill for CPU-bound phases while `phaseComplete` is false. Creeps toward
 * (but never reaches) the phase ceiling so the bar never sits at a false 100%.
 */
function softProcessingPercent(
  band: readonly [number, number],
  startedAt: number,
  now: number,
): number {
  const [lo, hi] = band;
  const ceiling = Math.max(lo, hi - 1);
  const elapsedMs = Math.max(0, now - startedAt);
  const t = 1 - Math.exp(-elapsedMs / 3500);
  return lo + (ceiling - lo) * Math.min(0.92, t);
}

/** Map live snapshot to a single 0–100 bar position across all payload phases. */
export function computeOverallPercent(
  snapshot: PayloadProgressSnapshot,
  now: number = Date.now(),
): number {
  const band = PHASE_BANDS[snapshot.phase];
  const [lo, hi] = band;

  if (isTransferPhase(snapshot.phase)) {
    const value = lerpBand(band, snapshot.bytesReceived, snapshot.totalBytes);
    if (snapshot.phaseComplete === false) {
      return Math.min(hi - 1, Math.max(lo, Math.round(value)));
    }
    return Math.min(100, Math.max(0, Math.round(value)));
  }

  if (snapshot.phaseComplete === true) {
    return hi;
  }

  // Default for verify/inflate/parse/finalize/install without an explicit complete
  // flag: treat as in-progress so a full-bytes emit cannot jump to 100% mid-work.
  return Math.min(hi - 1, Math.max(lo, Math.round(softProcessingPercent(band, snapshot.startedAt, now))));
}

export function isSoftMotionPhase(snapshot: PayloadProgressSnapshot): boolean {
  if (snapshot.phaseComplete === true) return false;
  if (isTransferPhase(snapshot.phase) && snapshot.phaseComplete !== false) return false;
  return true;
}

export function buildPayloadProgressViewModel(
  snapshot: PayloadProgressSnapshot,
  now: number = Date.now(),
): PayloadProgressViewModel {
  const rate = computeTransferRate(snapshot.bytesReceived, snapshot.startedAt, now);
  const eta = computeEtaSeconds(snapshot.bytesReceived, snapshot.totalBytes, rate);
  const phaseText = phaseLabel(snapshot.phase);
  const rateText = formatTransferRate(rate);
  const etaText = formatEta(eta);
  const showTransfer = isTransferPhase(snapshot.phase) && snapshot.phaseComplete !== false;
  const detailLine = showTransfer ? `${rateText} · ETA ${etaText}` : snapshot.fileName;
  return {
    overallPercent: computeOverallPercent(snapshot, now),
    phaseText,
    detailLine,
    etaText,
    rateText,
    fileName: snapshot.fileName,
    softMotion: isSoftMotionPhase(snapshot),
  };
}
