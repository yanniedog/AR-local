/** Live payload transfer / processing snapshot (real metrics only). */
export type PayloadProgressPhase = 'manifest' | 'download' | 'verify' | 'inflate' | 'parse';

export const PAYLOAD_PROGRESS_PHASES: PayloadProgressPhase[] = [
  'manifest',
  'download',
  'verify',
  'inflate',
  'parse',
];

/** Inclusive phase band on the overall 0–100 determinate bar. */
const PHASE_BANDS: Record<PayloadProgressPhase, readonly [number, number]> = {
  manifest: [0, 8],
  download: [8, 88],
  verify: [88, 92],
  inflate: [92, 96],
  parse: [96, 100],
};

export interface PayloadProgressSnapshot {
  phase: PayloadProgressPhase;
  fileName: string;
  bytesReceived: number;
  totalBytes: number | null;
  /** Epoch ms when the current transfer step started (for rate / ETA). */
  startedAt: number;
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
      return 'manifest';
    case 'download':
      return 'download';
    case 'verify':
      return 'verify sha256';
    case 'inflate':
      return 'decompress gzip';
    case 'parse':
      return 'parse json';
  }
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

/** Map live snapshot to a single 0–100 bar position across all payload phases. */
export function computeOverallPercent(snapshot: PayloadProgressSnapshot): number {
  const band = PHASE_BANDS[snapshot.phase];
  const value = lerpBand(band, snapshot.bytesReceived, snapshot.totalBytes);
  return Math.min(100, Math.max(0, Math.round(value)));
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
  const showTransfer = snapshot.phase === 'manifest' || snapshot.phase === 'download';
  const detailLine = showTransfer ? `${rateText} · ETA ${etaText}` : snapshot.fileName;
  return {
    overallPercent: computeOverallPercent(snapshot),
    phaseText,
    detailLine,
    etaText,
    rateText,
    fileName: snapshot.fileName,
  };
}
