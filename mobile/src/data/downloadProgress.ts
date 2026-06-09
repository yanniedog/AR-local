/** Live payload transfer / processing snapshot (real metrics only). */
export type PayloadProgressPhase = 'manifest' | 'download' | 'verify' | 'inflate' | 'parse';

export interface PayloadProgressSnapshot {
  phase: PayloadProgressPhase;
  fileName: string;
  bytesReceived: number;
  totalBytes: number | null;
  /** Epoch ms when the current transfer step started (for rate / ETA). */
  startedAt: number;
}

export type PayloadProgressHandler = (snapshot: PayloadProgressSnapshot) => void;

export function fileNameFromUrl(url: string): string {
  try {
    const path = new URL(url).pathname;
    const base = path.split('/').pop() ?? url;
    return decodeURIComponent(base);
  } catch {
    return url.split('/').pop() ?? url;
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
