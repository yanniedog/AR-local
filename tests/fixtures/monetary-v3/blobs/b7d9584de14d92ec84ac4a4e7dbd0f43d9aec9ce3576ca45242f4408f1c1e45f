import AsyncStorage from '@react-native-async-storage/async-storage';
import * as FileSystem from 'expo-file-system/legacy';
import * as SecureStore from 'expo-secure-store';

import { bridgeLogToCrashlytics } from './observability';
import {
  compactPerformanceAuditReportForLog,
} from './performanceAuditLog';
import {
  LEGACY_PERFORMANCE_AUDIT_STORAGE_KEYS,
  LATEST_PERFORMANCE_AUDIT_STORAGE_KEY,
  PERFORMANCE_AUDIT_SCHEMA_VERSION,
} from './performanceAuditSchema';
import { SECURE_STORE_KEYS } from './secureStoreKey';

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export interface LogEntry {
  ts: string;
  level: LogLevel;
  tag: string;
  message: string;
}

export const MAX_LOG_LINES = 2000;
export const MAX_LOG_BYTES = 512 * 1024;
export const PERSIST_TAIL_LINES = 100;
export const MAX_LOG_FILE_BYTES = 2 * 1024 * 1024;
export const MAX_LOG_DISPLAY_BYTES = 16 * 1024;
export const LOG_FILE_FLUSH_MS = 100;
export const ANDROID_PACKAGE = 'com.eyex.australianrates';
export const ANDROID_LOG_PATH_HINT = `Android/data/${ANDROID_PACKAGE}/files/logs/ar-local.log`;

const STORAGE_KEY = 'ar-debug-log-tail';
const LOG_DIR = `${FileSystem.documentDirectory ?? ''}logs/`;
const LOG_FILE = `${LOG_DIR}ar-local.log`;
export const DEBUG_LOG_SHARE_FILE = `${FileSystem.cacheDirectory ?? ''}ar-debug-log-share.txt`;
/** Full audit JSON kept beside the bounded ring so trim cannot drop the diagnosis. */
const PERFORMANCE_AUDIT_SIDECAR_FILE = `${LOG_DIR}ar-performance-audit-latest.json`;
export const DEBUG_LOG_UPLOAD_RECEIPT_KEY = SECURE_STORE_KEYS.debugLogUploadReceipt;

const SECRET_VALUE = String.raw`[^\s,;}"']+`;
const SECRET_SOURCES: string[] = [
  String.raw`EXPO_TOKEN[=:\s]${SECRET_VALUE}`,
  String.raw`Bearer\s+${SECRET_VALUE}`,
  String.raw`Authorization:\s*${SECRET_VALUE}`,
  String.raw`(?:api[_-]?key|secret|password|token)[=:\s]${SECRET_VALUE}`,
  String.raw`"(?:EXPO_TOKEN|api[_-]?key|secret|password|token)"\s*:\s*"[^"]+"`,
  String.raw`'(?:EXPO_TOKEN|api[_-]?key|secret|password|token)'\s*:\s*'[^']+'`,
];
/**
 * One alternation rather than six sequential passes. Redaction runs over the
 * whole megabyte-scale audit report and the whole 2MB log on the JS thread, so
 * each avoided pass is a full scan and a full string copy the UI thread no
 * longer waits on.
 */
const SECRET_PATTERN = new RegExp(SECRET_SOURCES.map((source) => `(?:${source})`).join('|'), 'gi');
const PRIVATE_IDENTIFIER_PATTERN =
  /\b(uid|user[_-]?id|subscription[_-]?id|subscriptionId)\s*[=:]\s*[^\s,;}"']+/gi;
const EMAIL_PATTERN = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi;

const LOG_LINE_RE = /^(\S+)\s+\[(\w+)\s*\]\s+([^:]+):\s(.*)$/;

/** Strip likely secrets before lines are stored or uploaded. */
export function redactSecrets(text: string): string {
  return text
    .replace(SECRET_PATTERN, (match) => {
      const key = match.split(/[=:\s]/)[0] ?? 'secret';
      return `${key}=[REDACTED]`;
    })
    .replace(PRIVATE_IDENTIFIER_PATTERN, (_match, key: string) => `${key}=[REDACTED]`)
    .replace(EMAIL_PATTERN, '[REDACTED_EMAIL]');
}

export function formatEntry(entry: LogEntry): string {
  const level = entry.level.toUpperCase().padEnd(5);
  return `${entry.ts} [${level}] ${entry.tag}: ${entry.message}`;
}

/**
 * Preserve the complete JS traceback in one physical log line so it survives
 * file-tail parsing and can be exported without orphaned stack frames.
 */
export function formatErrorTrace(error: unknown): string {
  let trace: string;
  if (error instanceof Error) {
    trace = error.stack ?? `${error.name}: ${error.message}`;
  } else {
    try {
      trace =
        typeof error === 'string'
          ? error
          : JSON.stringify(error) ?? String(error);
    } catch {
      trace = String(error);
    }
  }
  return trace.replace(/\r/g, '').replace(/\n/g, String.raw`\n`);
}

/** Parse a single persisted log line back into a LogEntry. */
export function parseLogLine(line: string): LogEntry | null {
  const match = line.match(LOG_LINE_RE);
  if (!match) return null;
  const level = match[2].toLowerCase() as LogLevel;
  if (!['debug', 'info', 'warn', 'error'].includes(level)) return null;
  return { ts: match[1], level, tag: match[3].trim(), message: redactSecrets(match[4]) };
}

function parseLogFile(text: string): LogEntry[] {
  const entries: LogEntry[] = [];
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    const entry = parseLogLine(line);
    if (entry) entries.push(entry);
  }
  return entries;
}

const textEncoder = new TextEncoder();

function entryBytes(entry: LogEntry): number {
  return textEncoder.encode(formatEntry(entry) + "\n").length;
}

const textDecoder = new TextDecoder();

function trimToBudget(content: string, maxBytes: number): string {
  const limit = Math.max(0, Math.floor(maxBytes));
  const bytes = textEncoder.encode(content);
  if (bytes.length <= limit) return content;
  if (limit === 0) return '';
  let start = bytes.length - limit;
  while (start < bytes.length && bytes[start] !== 0x0a) start += 1;
  start += 1;
  if (start >= bytes.length) return '';
  return textDecoder.decode(bytes.slice(start));
}

function trimFileTail(content: string): string {
  return trimToBudget(content, MAX_LOG_FILE_BYTES);
}

/**
 * Keep the interactive log screen cheap even when one structured audit report
 * occupies hundreds of KiB. This is display-only: copy/share/upload continue
 * to read the complete bounded in-memory log.
 */
export function formatLogDisplayTail(
  content: string,
  maxBytes = MAX_LOG_DISPLAY_BYTES,
): string {
  const limit = Math.max(0, Math.floor(maxBytes));
  const bytes = textEncoder.encode(content);
  if (bytes.length <= limit) return content;
  if (limit === 0) return '';
  const tail = textDecoder.decode(bytes.slice(bytes.length - limit));
  const newline = tail.indexOf('\n');
  const visible = newline >= 0 ? tail.slice(newline + 1) : tail;
  return `[Showing newest ${limit} bytes of ${bytes.length}; exports include the full log]\n${visible}`;
}

async function ensureLogDir(): Promise<void> {
  if (!FileSystem.documentDirectory) return;
  const info = await FileSystem.getInfoAsync(LOG_DIR);
  if (!info.exists) {
    await FileSystem.makeDirectoryAsync(LOG_DIR, { intermediates: true });
  }
}

let pendingFileLines: string[] = [];
let fileFlushTimer: ReturnType<typeof setTimeout> | null = null;
let fileFlushPromise: Promise<void> | null = null;
let fileContentCache: string | null = null;
/** Byte size of the on-disk log, so appends never need to read it back. */
let fileByteLength: number | null = null;
let fileWriteEpoch = 0;
let coldStartResetPromise: Promise<void> | null = null;
type NativeFileAccessModule = {
  FileSystem?: { appendFile?: (path: string, data: string, encoding?: string) => Promise<void> };
};
let nativeFileAccessModule: NativeFileAccessModule | null | undefined;

function scheduleFileFlush(): void {
  if (fileFlushTimer) return;
  // Resolve the optional native bridge while the caller's module environment
  // is still alive. Deferring the first lazy require into the timer lets a
  // short-lived consumer (notably Jest, but also a fast native teardown) begin
  // shutdown before the append implementation is loaded.
  nativeAppendFile();
  fileFlushTimer = setTimeout(() => {
    fileFlushTimer = null;
    void flushPendingToFile();
  }, LOG_FILE_FLUSH_MS);
}

/**
 * Native append, when the platform provides one. Rewriting the whole file per
 * flush cost a full concat plus a full TextEncoder pass on the JS thread every
 * time — and the performance audit forces a physical flush after each of its
 * ~260 checks, so that quadratic cost dominated the entire run and left the JS
 * thread saturated before the final report was even serialized.
 */
function nativeAppendFile(): ((path: string, data: string) => Promise<void>) | null {
  if (nativeFileAccessModule === undefined) {
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports -- optional native bridge
      nativeFileAccessModule = require('react-native-file-access') as NativeFileAccessModule;
    } catch {
      nativeFileAccessModule = null;
    }
  }
  const append = nativeFileAccessModule?.FileSystem?.appendFile;
  if (typeof append !== 'function') return null;
  return (path, data) => append(path, data, 'utf8');
}

async function rewriteLogFile(appendText: string, epoch: number): Promise<void> {
  const existing = fileContentCache ?? (await FileSystem.readAsStringAsync(LOG_FILE).catch(() => ''));
  if (epoch !== fileWriteEpoch) return;
  const combined = trimFileTail(existing + appendText);
  await FileSystem.writeAsStringAsync(LOG_FILE, combined);
  if (epoch !== fileWriteEpoch) return;
  fileContentCache = combined;
  fileByteLength = textEncoder.encode(combined).length;
}

async function syncLogFile(appendText: string, epoch: number): Promise<void> {
  if (!FileSystem.documentDirectory) {
    throw new Error('documentDirectory unavailable');
  }
  await ensureLogDir();
  const append = nativeAppendFile();
  if (!append) {
    await rewriteLogFile(appendText, epoch);
    return;
  }
  if (fileByteLength == null) {
    const existing = fileContentCache
      ?? (await FileSystem.readAsStringAsync(LOG_FILE).catch(() => ''));
    if (epoch !== fileWriteEpoch) return;
    fileByteLength = textEncoder.encode(existing).length;
  }
  const appendBytes = textEncoder.encode(appendText).length;
  // Only a rollover needs the whole file in memory; ordinary flushes touch
  // nothing but the bytes they add.
  if (fileByteLength + appendBytes > MAX_LOG_FILE_BYTES) {
    await rewriteLogFile(appendText, epoch);
    return;
  }
  try {
    await append(LOG_FILE, appendText);
  } catch {
    // A missing/rotated file or an unavailable native module must still land
    // this batch; the rewrite path creates the file from scratch.
    await rewriteLogFile(appendText, epoch);
    return;
  }
  if (epoch !== fileWriteEpoch) return;
  fileByteLength += appendBytes;
  // The cache would need a full concat to stay correct; readers re-read instead.
  fileContentCache = null;
}

async function flushPendingToFile(requirePhysical = false): Promise<void> {
  // The UI cold-start reset owns the file until stale content is deleted.
  // New-session entries remain queued and are written immediately afterwards.
  if (coldStartResetPromise) await coldStartResetPromise;
  if (fileFlushPromise) {
    await fileFlushPromise;
    if (pendingFileLines.length === 0) return;
  }

  const batch = pendingFileLines.splice(0);
  if (batch.length === 0) return;
  const epoch = fileWriteEpoch;

  fileFlushPromise = (async () => {
    try {
      if (!FileSystem.documentDirectory) {
        pendingFileLines.unshift(...batch);
        if (requirePhysical) throw new Error('documentDirectory unavailable');
        return;
      }
      await syncLogFile(batch.join(''), epoch);
    } catch (error) {
      if (epoch === fileWriteEpoch) {
        pendingFileLines.unshift(...batch);
      }
      if (requirePhysical) throw error;
    } finally {
      fileFlushPromise = null;
    }
  })();

  await fileFlushPromise;
}

export class RingBuffer {
  private entries: { entry: LogEntry; sequence: number }[] = [];
  private bytes = 0;
  private nextSequence = 1;

  append(entry: LogEntry): void {
    this.entries.push({ entry, sequence: this.nextSequence });
    this.nextSequence += 1;
    this.bytes += entryBytes(entry);
    while (
      this.entries.length > MAX_LOG_LINES ||
      this.bytes > MAX_LOG_BYTES
    ) {
      const removed = this.entries.shift();
      if (!removed) break;
      this.bytes -= entryBytes(removed.entry);
    }
  }

  clear(): void {
    this.entries = [];
    this.bytes = 0;
  }

  loadHistory(history: LogEntry[]): void {
    const merged = [...history, ...this.entries.map(({ entry }) => entry)];
    merged.sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
    this.entries = [];
    this.bytes = 0;
    for (const entry of merged) {
      this.append(entry);
    }
  }

  getEntries(): LogEntry[] {
    return this.entries.map(({ entry }) => entry);
  }

  getCursor(): number {
    return this.nextSequence - 1;
  }

  getEntriesAfter(cursor: number): LogEntry[] {
    return this.entries
      .filter(({ sequence }) => sequence > cursor)
      .map(({ entry }) => entry);
  }

  getText(): string {
    return this.entries.map(({ entry }) => formatEntry(entry)).join('\n');
  }

  getDisplayText(maxBytes = MAX_LOG_DISPLAY_BYTES): string {
    const limit = Math.max(0, Math.floor(maxBytes));
    if (limit === 0 || this.entries.length === 0) return '';
    const fullBytes = Math.max(0, this.bytes - 1);
    if (fullBytes <= limit) return this.getText();

    const visible: string[] = [];
    let visibleBytes = 0;
    for (let index = this.entries.length - 1; index >= 0; index -= 1) {
      const line = formatEntry(this.entries[index].entry);
      const lineBytes = textEncoder.encode(line).length;
      const separatorBytes = visible.length ? 1 : 0;
      if (lineBytes + separatorBytes + visibleBytes > limit) {
        if (visible.length === 0) {
          const bytes = textEncoder.encode(line);
          let start = Math.max(0, bytes.length - limit);
          while (start < bytes.length && (bytes[start] & 0xc0) === 0x80) start += 1;
          visible.push(textDecoder.decode(bytes.slice(start)));
        }
        break;
      }
      visible.unshift(line);
      visibleBytes += lineBytes + separatorBytes;
    }
    return `[Showing newest ${limit} bytes of ${fullBytes}; exports include the full log]\n${visible.join('\n')}`;
  }

  size(): number {
    return this.entries.length;
  }
}

type Listener = () => void;

const buffer = new RingBuffer();
const listeners = new Set<Listener>();
let persistTimer: ReturnType<typeof setTimeout> | null = null;
let clearState: 'ready' | 'clearing' | 'failed' = 'ready';
let clearPromise: Promise<void> | null = null;

function notify(): void {
  for (const fn of listeners) fn();
}

function schedulePersist(): void {
  if (persistTimer) return;
  persistTimer = setTimeout(() => {
    persistTimer = null;
    void persistTail();
  }, 500);
}

async function persistTail(): Promise<void> {
  try {
    const tail = buffer.getEntries().slice(-PERSIST_TAIL_LINES);
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(tail));
  } catch {
    // non-fatal
  }
}

function append(level: LogLevel, tag: string, message: string): void {
  // Collapse real newlines so stack traces and audit dumps stay one parseable
  // physical line (callers may also pre-escape via formatErrorTrace).
  const messageRedacted = redactSecrets(
    String(message).replace(/\r/g, '').replace(/\n/g, String.raw`\n`),
  );
  const entry: LogEntry = {
    ts: new Date().toISOString(),
    level,
    tag,
    message: messageRedacted,
  };
  buffer.append(entry);
  pendingFileLines.push(formatEntry(entry) + '\n');
  // Performance reports can be large and include device/app timing context.
  // Keep them local even when general Crashlytics diagnostics are enabled;
  // sharing remains an explicit action from the Debug log screen.
  if (tag !== 'perf-audit') {
    bridgeLogToCrashlytics(level, tag, messageRedacted);
  }
  notify();
  // Audit checkpoints are explicitly flushed by the runner. Avoid scheduling
  // a large AsyncStorage tail serialization in the middle of the next measured
  // navigation phase.
  if (clearState === 'ready') {
    if (tag !== 'perf-audit') schedulePersist();
    scheduleFileFlush();
  }
}

interface StoredPerformanceAudit {
  schemaVersion: typeof PERFORMANCE_AUDIT_SCHEMA_VERSION | 6;
  summaryMarker: string;
  reportJson: string;
}

const PERFORMANCE_AUDIT_REPORT_BEGIN = 'PERFORMANCE_AUDIT_REPORT_BEGIN';
const PERFORMANCE_AUDIT_REPORT_JSON = 'PERFORMANCE_AUDIT_REPORT_JSON';
const PERFORMANCE_AUDIT_REPORT_END = 'PERFORMANCE_AUDIT_REPORT_END';
const PERFORMANCE_AUDIT_REPORT_SIDECAR = 'PERFORMANCE_AUDIT_REPORT_SIDECAR';

function physicalAuditMarker(summaryMarker: string): string {
  return `${PERFORMANCE_AUDIT_REPORT_BEGIN} ${summaryMarker}`;
}

function isPerformanceAuditReportLine(line: string): boolean {
  return (
    line.includes(PERFORMANCE_AUDIT_REPORT_BEGIN) ||
    line.includes(PERFORMANCE_AUDIT_REPORT_JSON) ||
    line.includes(PERFORMANCE_AUDIT_REPORT_END) ||
    line.includes(PERFORMANCE_AUDIT_REPORT_SIDECAR)
  );
}

/** Drop prior audit dump lines so a new reserved-tail write does not stack blocks. */
function stripPerformanceAuditReportLines(content: string): string {
  if (!content) return '';
  // Splitting and rejoining a 2MB log costs two more full copies. Almost every
  // flush has no audit block to strip, so check before paying for it.
  if (
    !content.includes(PERFORMANCE_AUDIT_REPORT_BEGIN) &&
    !content.includes(PERFORMANCE_AUDIT_REPORT_JSON) &&
    !content.includes(PERFORMANCE_AUDIT_REPORT_END) &&
    !content.includes(PERFORMANCE_AUDIT_REPORT_SIDECAR)
  ) {
    return content;
  }
  const hadTrailingNewline = content.endsWith('\n');
  const kept = content
    .split('\n')
    .filter((line) => line.length > 0 && !isPerformanceAuditReportLine(line));
  if (kept.length === 0) return '';
  return kept.join('\n') + (hadTrailingNewline ? '\n' : '');
}

function ensureTrailingNewline(content: string): string {
  if (!content) return '';
  return content.endsWith('\n') ? content : `${content}\n`;
}

/**
 * AsyncStorage is SQLite-backed on Android and a multi-megabyte row is exactly
 * what makes later reads blow the cursor window. The sidecar file already holds
 * the full body, so oversized snapshots are skipped instead of stored, and any
 * previous snapshot is dropped so a stale smaller audit cannot look like the
 * newest one.
 */
export const MAX_AUDIT_SNAPSHOT_STORAGE_CHARS = 128 * 1024;
/** Body budget leaving room for JSON escaping to expand the stored record. */
export const MAX_AUDIT_SNAPSHOT_BODY_CHARS = Math.floor(MAX_AUDIT_SNAPSHOT_STORAGE_CHARS / 2);
/**
 * Bounds only the recovery copy this module *appends* to an export when the
 * physical log no longer carries the audit block. The log itself is already
 * capped at MAX_LOG_FILE_BYTES, so a block the log did keep is returned as-is:
 * re-splitting a 2MB log to strip it would cost exactly the extra full copies
 * this path exists to avoid.
 */
export const MAX_APPENDED_AUDIT_REPORT_CHARS = 512 * 1024;

async function removeLegacyPerformanceAuditSnapshots(): Promise<void> {
  await Promise.all(
    LEGACY_PERFORMANCE_AUDIT_STORAGE_KEYS
      // Schema v6 remains available to the compatibility reader. Only the
      // obsolete v5 snapshot is discarded automatically.
      .filter((key) => key.endsWith('-v5'))
      .map((key) =>
      AsyncStorage.removeItem(key).catch(() => {})),
  );
}

async function storeLatestAuditSnapshot(stored: StoredPerformanceAudit): Promise<void> {
  await removeLegacyPerformanceAuditSnapshots();
  // Measure the body directly: serializing an oversized record only to discard
  // it allocated another full copy of the report on the blocking path. The
  // record that actually lands is JSON.stringify(stored), which escapes every
  // quote in a quote-dense report body and carries summaryMarker too, so budget
  // the body at half the record limit rather than against it.
  if (stored.reportJson.length > MAX_AUDIT_SNAPSHOT_BODY_CHARS) {
    await AsyncStorage.removeItem(LATEST_PERFORMANCE_AUDIT_STORAGE_KEY).catch(() => {});
    return;
  }
  try {
    await AsyncStorage.setItem(LATEST_PERFORMANCE_AUDIT_STORAGE_KEY, JSON.stringify(stored));
  } catch {
    // non-fatal once the sidecar exists
  }
}

/** Writes the sidecar and returns its byte length so durability can be checked by size. */
async function writePerformanceAuditSidecar(stored: StoredPerformanceAudit): Promise<number> {
  if (!FileSystem.documentDirectory) return 0;
  await ensureLogDir();
  const payload = JSON.stringify(stored);
  await FileSystem.writeAsStringAsync(PERFORMANCE_AUDIT_SIDECAR_FILE, payload);
  return textEncoder.encode(payload).length;
}

/**
 * Existence and size must stay distinguishable: a platform that does not report
 * a size is fine to skip comparing, but a file that is not there at all is a
 * failed write, and the sidecar is the only copy of the report body.
 */
async function statFile(path: string): Promise<{ exists: boolean; size: number | null }> {
  try {
    const info = await FileSystem.getInfoAsync(path);
    if (!info.exists) return { exists: false, size: null };
    const size = (info as { size?: number }).size;
    return { exists: true, size: typeof size === 'number' ? size : null };
  } catch {
    return { exists: false, size: null };
  }
}

async function readPerformanceAuditSidecar(): Promise<StoredPerformanceAudit | null> {
  if (!FileSystem.documentDirectory) return null;
  try {
    const raw = await FileSystem.readAsStringAsync(PERFORMANCE_AUDIT_SIDECAR_FILE);
    return parseStoredPerformanceAudit(raw);
  } catch {
    return null;
  }
}

/**
 * Persist the complete audit block at the end of the physical log, reserving
 * enough budget so begin/json/end cannot be sliced mid-line by the 2MB trim.
 */
async function writeReservedPerformanceAuditBlock(
  blockText: string,
  epoch: number,
): Promise<void> {
  if (!FileSystem.documentDirectory) {
    throw new Error('documentDirectory unavailable');
  }
  await ensureLogDir();
  const existing = fileContentCache ?? (await FileSystem.readAsStringAsync(LOG_FILE).catch(() => ''));
  if (epoch !== fileWriteEpoch) return;
  const cleaned = ensureTrailingNewline(stripPerformanceAuditReportLines(existing));
  const blockBytes = textEncoder.encode(blockText).length;
  if (blockBytes > MAX_LOG_FILE_BYTES) {
    throw new Error(
      `Performance audit block (${blockBytes} bytes) exceeds the ${MAX_LOG_FILE_BYTES}-byte physical log budget`,
    );
  }
  const head = trimToBudget(cleaned, MAX_LOG_FILE_BYTES - blockBytes);
  const combined = ensureTrailingNewline(head) + blockText;
  await FileSystem.writeAsStringAsync(LOG_FILE, combined);
  if (epoch !== fileWriteEpoch) return;
  fileContentCache = combined;
  fileByteLength = textEncoder.encode(combined).length;
}

function parseStoredPerformanceAudit(
  raw: string | null,
  expectedSchema: typeof PERFORMANCE_AUDIT_SCHEMA_VERSION | 6 = PERFORMANCE_AUDIT_SCHEMA_VERSION,
): StoredPerformanceAudit | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<StoredPerformanceAudit>;
    if (
      value.schemaVersion !== expectedSchema ||
      typeof value.summaryMarker !== 'string' ||
      typeof value.reportJson !== 'string'
    ) return null;
    return {
      schemaVersion: expectedSchema,
      summaryMarker: redactSecrets(value.summaryMarker),
      reportJson: redactSecrets(value.reportJson),
    };
  } catch {
    return null;
  }
}

const VALID_LOG_LEVELS: LogLevel[] = ['debug', 'info', 'warn', 'error'];

function isValidEntry(entry: unknown): entry is LogEntry {
  if (!entry || typeof entry !== 'object') return false;
  const e = entry as Partial<LogEntry>;
  if (typeof e.ts !== 'string' || !e.ts) return false;
  if (typeof e.level !== 'string' || !VALID_LOG_LEVELS.includes(e.level as LogLevel)) return false;
  if (typeof e.tag !== 'string' || !e.tag) return false;
  if (typeof e.message !== 'string') return false;
  return true;
}

export const debugLog = {
  debug(tag: string, message: string): void {
    append('debug', tag, message);
  },
  info(tag: string, message: string): void {
    append('info', tag, message);
  },
  warn(tag: string, message: string): void {
    append('warn', tag, message);
  },
  error(tag: string, message: string): void {
    append('error', tag, message);
    void flushPendingToFile();
  },
  /**
   * Start one fresh log session for this UI process. Memory is cleared
   * synchronously before any startup entry can be appended; disk cleanup runs
   * ahead of the first flush. Reopening an existing backgrounded process does
   * not reload this module, so its current session remains intact.
   */
  beginColdStartSession(): Promise<void> {
    if (coldStartResetPromise) return coldStartResetPromise;
    fileWriteEpoch += 1;
    buffer.clear();
    pendingFileLines = [];
    fileContentCache = null;
    fileByteLength = null;
    if (fileFlushTimer) {
      clearTimeout(fileFlushTimer);
      fileFlushTimer = null;
    }
    const inFlight = fileFlushPromise;
    fileFlushPromise = null;
    notify();
    coldStartResetPromise = (async () => {
      if (inFlight) await inFlight.catch(() => {});
      await AsyncStorage.removeItem(STORAGE_KEY).catch(() => {});
      await FileSystem.deleteAsync(LOG_FILE, { idempotent: true }).catch(() => {});
      // The audit sidecar deliberately survives. A run that crashes the app is
      // precisely when its report matters, and deleting the sidecar on the next
      // launch destroyed the only copy before anyone could read it — which is
      // how a crashed 259-check audit left no trace at all. The AsyncStorage
      // snapshot already persists across launches; this matches it. An explicit
      // `clear()` still removes both.
    })();
    return coldStartResetPromise;
  },
  clear(): Promise<void> {
    if (clearPromise) return clearPromise;
    clearState = 'clearing';
    fileWriteEpoch += 1;
    buffer.clear();
    pendingFileLines = [];
    fileContentCache = null;
    fileByteLength = null;
    if (persistTimer) {
      clearTimeout(persistTimer);
      persistTimer = null;
    }
    if (fileFlushTimer) {
      clearTimeout(fileFlushTimer);
      fileFlushTimer = null;
    }
    const inFlight = fileFlushPromise;
    fileFlushPromise = null;
    notify();
    clearPromise = (async () => {
      try {
        if (inFlight) await inFlight;
        if (coldStartResetPromise) await coldStartResetPromise;
        const storageKeys = [
          STORAGE_KEY,
          LATEST_PERFORMANCE_AUDIT_STORAGE_KEY,
          ...LEGACY_PERFORMANCE_AUDIT_STORAGE_KEYS,
        ];
        await Promise.all(storageKeys.map((key) => AsyncStorage.removeItem(key)));
        const filePaths = [
          LOG_FILE,
          PERFORMANCE_AUDIT_SIDECAR_FILE,
          ...(FileSystem.cacheDirectory ? [DEBUG_LOG_SHARE_FILE] : []),
        ];
        await Promise.all(filePaths.map((path) =>
          FileSystem.deleteAsync(path, { idempotent: true })));

        const retainedStorageKeys = (
          await Promise.all(storageKeys.map(async (key) => (
            (await AsyncStorage.getItem(key)) == null ? null : key
          )))
        ).filter((key): key is string => key != null);
        const retainedFiles = (
          await Promise.all(filePaths.map(async (path) => (
            (await FileSystem.getInfoAsync(path)).exists ? path : null
          )))
        ).filter((path): path is string => path != null);
        if (retainedStorageKeys.length || retainedFiles.length) {
          throw new Error(
            `Clear verification found retained diagnostics: ` +
            [...retainedStorageKeys, ...retainedFiles].join(', '),
          );
        }
        clearState = 'ready';
        if (buffer.getEntries().length > 0) schedulePersist();
        if (pendingFileLines.length > 0) scheduleFileFlush();
      } catch (error) {
        clearState = 'failed';
        throw new Error(
          `Debug log clear is incomplete; exporting is blocked until Clear succeeds. ` +
          `${error instanceof Error ? error.message : String(error)}`,
        );
      } finally {
        clearPromise = null;
      }
    })();
    return clearPromise;
  },
  getText(): string {
    return buffer.getText();
  },
  getDisplayText(maxBytes = MAX_LOG_DISPLAY_BYTES): string {
    return buffer.getDisplayText(maxBytes);
  },
  getEntries(): LogEntry[] {
    return buffer.getEntries();
  },
  getCursor(): number {
    return buffer.getCursor();
  },
  getEntriesAfter(cursor: number): LogEntry[] {
    return buffer.getEntriesAfter(cursor);
  },
  getLogFileUri(): string {
    return LOG_FILE;
  },
  getAndroidLogPathHint(): string {
    return ANDROID_LOG_PATH_HINT;
  },
  async flushToFile(requirePhysical = false): Promise<void> {
    if (fileFlushTimer) {
      clearTimeout(fileFlushTimer);
      fileFlushTimer = null;
    }
    await flushPendingToFile(requirePhysical);
  },
  /**
   * Persist the canonical complete audit to its sidecar file and record a
   * crash-detectable begin/sidecar/end block in the physical diagnostic log.
   *
   * The report body itself lives in exactly one place: the sidecar. Writing a
   * second compacted copy into the log meant compacting the whole object graph,
   * re-serializing it, re-redacting it, appending a megabyte log entry (encoded
   * twice for ring accounting), and reserving that many bytes at the file tail —
   * a dozen megabyte-scale synchronous bursts on the JS thread while the user
   * watched a frozen 100% progress bar. `onStage` lets the caller surface each
   * remaining step and yield the thread between them.
   */
  async storePerformanceAudit(
    summaryMarker: string,
    report: unknown,
    onStage: (stage: string) => Promise<void> | void = () => {},
  ): Promise<void> {
    await onStage('Serializing the report');
    const stored: StoredPerformanceAudit = {
      schemaVersion: PERFORMANCE_AUDIT_SCHEMA_VERSION,
      summaryMarker: redactSecrets(summaryMarker),
      reportJson: redactSecrets(JSON.stringify(report)),
    };
    // Sidecar first: AsyncStorage can fail after a durable disk write; reverse order
    // would leave neither physical artifact when setItem throws.
    await onStage('Saving the complete report');
    const sidecarBytes = await writePerformanceAuditSidecar(stored);
    await storeLatestAuditSnapshot(stored);

    await onStage('Recording the report in the log');
    const beginMessage = physicalAuditMarker(stored.summaryMarker);
    const endMessage = `${PERFORMANCE_AUDIT_REPORT_END} ${stored.summaryMarker}`;
    const sidecarMessage = `${PERFORMANCE_AUDIT_REPORT_SIDECAR} ${PERFORMANCE_AUDIT_SIDECAR_FILE}`;
    const blockEntries: LogEntry[] = [beginMessage, sidecarMessage, endMessage].map(
      (message) => ({
        ts: new Date().toISOString(),
        level: 'info' as const,
        tag: 'perf-audit',
        message,
      }),
    );
    for (const entry of blockEntries) {
      buffer.append(entry);
    }
    notify();

    // Flush ordinary pending lines first so the reserved audit write sees a
    // coherent head, then pin the complete block at the file tail.
    if (fileFlushTimer) {
      clearTimeout(fileFlushTimer);
      fileFlushTimer = null;
    }
    await flushPendingToFile(FileSystem.documentDirectory != null);
    if (FileSystem.documentDirectory) {
      const epoch = fileWriteEpoch;
      const blockText = blockEntries.map((entry) => `${formatEntry(entry)}\n`).join('');
      await writeReservedPerformanceAuditBlock(blockText, epoch);
      await onStage('Verifying the saved report');
      // Verify durability by size, not by content. Reading the log back and
      // re-parsing plus re-redacting the sidecar re-processed the very bytes
      // just written — a megabyte of synchronous JS-thread work that blocked
      // long enough for Android to raise its "isn't responding" dialog. Both
      // writes throw on failure, so what is left to prove is that the bytes
      // landed whole, and a stat answers that in constant time.
      const [logStat, sidecarStat] = await Promise.all([
        statFile(LOG_FILE),
        statFile(PERFORMANCE_AUDIT_SIDECAR_FILE),
      ]);
      // Both files must be present. Sizes are compared only when the platform
      // reports them, so a stat without a size degrades to an existence check
      // rather than silently passing a truncated write.
      const logOk = logStat.exists
        && (logStat.size == null || fileByteLength == null || logStat.size === fileByteLength);
      const sidecarOk = sidecarStat.exists
        && (sidecarStat.size == null || sidecarStat.size === sidecarBytes);
      if (!logOk || !sidecarOk) {
        throw new Error('Complete performance audit was not verified in the physical log file');
      }
    }
  },
  /** Read the flushed on-disk log plus a paste-sized audit snapshot. */
  async readCompleteText(): Promise<string> {
    if (clearState !== 'ready') {
      throw new Error('Debug log export is blocked until the incomplete Clear operation succeeds.');
    }
    const exportEpoch = fileWriteEpoch;
    const assertExportCurrent = () => {
      if (clearState !== 'ready' || fileWriteEpoch !== exportEpoch) {
        throw new Error('Debug log export was cancelled because Clear started while it was being prepared.');
      }
    };
    if (fileFlushTimer) {
      clearTimeout(fileFlushTimer);
      fileFlushTimer = null;
    }
    await flushPendingToFile();
    assertExportCurrent();
    const text = !FileSystem.documentDirectory
      ? buffer.getText()
      : await FileSystem.readAsStringAsync(LOG_FILE).catch(() => buffer.getText());
    assertExportCurrent();
    const clean = redactSecrets(text);
    await removeLegacyPerformanceAuditSnapshots();
    assertExportCurrent();
    // Prefer the sidecar so a failed/stale AsyncStorage write cannot hide a newer disk report.
    const latest =
      (await readPerformanceAuditSidecar()) ??
      parseStoredPerformanceAudit(
        await AsyncStorage.getItem(LATEST_PERFORMANCE_AUDIT_STORAGE_KEY).catch(() => null),
      ) ??
      parseStoredPerformanceAudit(
        await AsyncStorage.getItem(
          LEGACY_PERFORMANCE_AUDIT_STORAGE_KEYS.find((key) => key.endsWith('-v6'))!,
        ).catch(() => null),
        6,
      );
    assertExportCurrent();
    if (!latest) return clean;
    // The physical log carries only the begin/sidecar/end markers, so an export
    // always appends the body from the sidecar. Compaction happens here rather
    // than during persistence: by the time anything reads a complete export the
    // report is already durable and the audit screen already has its results.
    let compactJson: string;
    try {
      compactJson = redactSecrets(
        JSON.stringify(compactPerformanceAuditReportForLog(JSON.parse(latest.reportJson))),
      );
    } catch {
      compactJson = latest.reportJson;
    }
    const complete = [
      clean,
      '',
      '# Latest complete performance audit',
      latest.summaryMarker,
      compactJson.length > MAX_APPENDED_AUDIT_REPORT_CHARS
        // An export that carries a body this large is rejected by the paste
        // service anyway, and building it costs several full copies of the log.
        ? `${PERFORMANCE_AUDIT_REPORT_SIDECAR} ${PERFORMANCE_AUDIT_SIDECAR_FILE} ` +
          `(compact report omitted from this export: ${compactJson.length} chars)`
        : compactJson,
    ].join('\n');
    assertExportCurrent();
    return complete;
  },
  subscribe(fn: Listener): () => void {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
  async restoreFromStorage(): Promise<void> {
    const restored: LogEntry[] = [];

    try {
      if (FileSystem.documentDirectory) {
        await ensureLogDir();
        const info = await FileSystem.getInfoAsync(LOG_FILE);
        if (info.exists) {
          const text = await FileSystem.readAsStringAsync(LOG_FILE);
          fileContentCache = text;
          fileByteLength = textEncoder.encode(text).length;
          restored.push(...parseLogFile(text).slice(-MAX_LOG_LINES));
        }
      }
    } catch {
      // non-fatal
    }

    if (restored.length === 0) {
      try {
        const raw = await AsyncStorage.getItem(STORAGE_KEY);
        if (raw) {
          const tail = JSON.parse(raw) as LogEntry[];
          if (Array.isArray(tail)) {
            restored.push(...tail.filter(isValidEntry));
          }
        }
      } catch {
        // ignore corrupt snapshot
      }
    }

    if (restored.length === 0) return;
    // Startup logging may have flushed to the same file while this deferred
    // read was in flight. Do not merge those exact current-session entries a
    // second time into the bounded diagnostic buffer.
    const liveLines = new Set(buffer.getEntries().map(formatEntry));
    buffer.loadHistory(restored.filter((entry) => !liveLines.has(formatEntry(entry))));
    notify();
  },
};

/** Format log bundle for paste.rs upload (header + body). */
export function formatLogUploadBody(entriesText: string, meta?: Record<string, string>): string {
  const lines = ['# AR-app mobile debug log', `generated=${new Date().toISOString()}`];
  if (meta) {
    for (const [key, value] of Object.entries(meta)) {
      lines.push(redactSecrets(`${key}=${value}`));
    }
  }
  // Re-redact at the export boundary so logs restored from an older app build
  // receive the current privacy rules too.
  lines.push('', redactSecrets(entriesText));
  return lines.join('\n');
}

/** Canonical export wrapper: every exported artifact identifies its installed build. */
export function formatVersionedLogExport(
  entriesText: string,
  appVersion: string,
  buildVersion: string,
  meta: Record<string, string> = {},
): string {
  return formatLogUploadBody(entriesText, {
    ...meta,
    app_version: appVersion,
    build_version: buildVersion,
  });
}

export const PASTE_RS_URL = 'https://paste.rs/';
export const PASTE_CNET_URL = 'https://paste.c-net.org/';
export const PASTE_RS_ATTEMPT_TIMEOUT_MS = 20_000;
export const PASTE_RS_TAIL_MAX_BYTES = 128 * 1024;
/** Live paste.rs accepts only this many bytes without returning a partial paste. */
export const PASTE_RS_MAX_FULL_UPLOAD_BYTES = 384 * 1024;

const PASTE_RS_RETRY_BACKOFF_MS = 1_000;
const PASTE_RS_MAX_RETRY_DELAY_MS = 5_000;

export interface PasteRsUploadResult {
  url: string;
  /** paste.rs returned 206 and truncated the submitted body. */
  truncated: boolean;
  /** The client submitted only the newest log tail after two transient failures. */
  clientTruncated: boolean;
  attempts: number;
  originalBytes: number;
  uploadedBytes: number;
}

export interface DebugLogUploadResult extends PasteRsUploadResult {
  provider: 'paste.rs' | 'paste.c-net.org';
  /** Present only for paste.c-net.org and persisted in SecureStore for deletion. */
  deleteKey?: string;
}

export interface DebugLogUploadReceipt {
  schemaVersion: 1;
  url: string;
  provider: DebugLogUploadResult['provider'];
  deleteKey?: string;
  createdAt: string;
}

function validateDebugLogUploadReceipt(value: unknown): DebugLogUploadReceipt {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('The saved upload deletion receipt is invalid.');
  }
  const receipt = value as Partial<DebugLogUploadReceipt>;
  let parsed: URL;
  try {
    parsed = new URL(receipt.url ?? '');
  } catch {
    throw new Error('The saved upload deletion receipt has an invalid URL.');
  }
  const expectedProvider = parsed.origin === new URL(PASTE_RS_URL).origin
    ? 'paste.rs'
    : parsed.origin === new URL(PASTE_CNET_URL).origin
      ? 'paste.c-net.org'
      : null;
  if (
    receipt.schemaVersion !== 1 ||
    expectedProvider == null ||
    parsed.protocol !== 'https:' ||
    parsed.username !== '' ||
    parsed.password !== '' ||
    receipt.provider !== expectedProvider ||
    typeof receipt.createdAt !== 'string' ||
    !Number.isFinite(Date.parse(receipt.createdAt)) ||
    (expectedProvider === 'paste.c-net.org' &&
      (typeof receipt.deleteKey !== 'string' || !receipt.deleteKey)) ||
    (receipt.deleteKey != null && typeof receipt.deleteKey !== 'string')
  ) {
    throw new Error('The saved upload deletion receipt is invalid.');
  }
  return {
    schemaVersion: 1,
    url: parsed.toString(),
    provider: expectedProvider,
    ...(receipt.deleteKey ? { deleteKey: receipt.deleteKey } : {}),
    createdAt: receipt.createdAt,
  };
}

export async function saveDebugLogUploadReceipt(
  result: Pick<DebugLogUploadResult, 'url' | 'provider' | 'deleteKey'>,
  createdAt = new Date().toISOString(),
): Promise<DebugLogUploadReceipt> {
  const receipt = validateDebugLogUploadReceipt({
    schemaVersion: 1,
    url: result.url,
    provider: result.provider,
    ...(result.deleteKey ? { deleteKey: result.deleteKey } : {}),
    createdAt,
  });
  await SecureStore.setItemAsync(DEBUG_LOG_UPLOAD_RECEIPT_KEY, JSON.stringify(receipt), {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  });
  return receipt;
}

export async function loadDebugLogUploadReceipt(): Promise<DebugLogUploadReceipt | null> {
  const raw = await SecureStore.getItemAsync(DEBUG_LOG_UPLOAD_RECEIPT_KEY);
  if (raw == null) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error('The saved upload deletion receipt cannot be read.');
  }
  return validateDebugLogUploadReceipt(parsed);
}

export interface PasteRsUploadOptions {
  attemptTimeoutMs?: number;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
}

type PasteRsFailureKind =
  | 'timeout'
  | 'network'
  | 'rate-limit'
  | 'server'
  | 'client'
  | 'invalid-response';

class PasteRsAttemptError extends Error {
  constructor(
    readonly kind: PasteRsFailureKind,
    readonly status?: number,
    readonly responseBody = '',
    readonly retryAfter?: string | null,
  ) {
    super(kind);
    this.name = 'PasteRsAttemptError';
  }

  get transient(): boolean {
    return (
      this.kind === 'timeout' ||
      this.kind === 'network' ||
      this.kind === 'rate-limit' ||
      this.kind === 'server'
    );
  }
}

export class PasteRsUploadError extends Error {
  constructor(
    message: string,
    readonly attempts: number,
  ) {
    super(message);
    this.name = 'PasteRsUploadError';
  }
}

function sanitizePasteRsResponse(raw: string): string {
  return raw
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&amp;/gi, '&')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 120);
}

function friendlyPasteRsError(error: PasteRsAttemptError): string {
  switch (error.kind) {
    case 'timeout':
      return 'paste.rs did not respond in time. Try again, or use Share or Copy instead.';
    case 'network':
      return 'Could not reach paste.rs. Check your connection, then try again or use Share or Copy instead.';
    case 'rate-limit':
      return 'paste.rs is rate-limiting uploads. Try again later, or use Share or Copy instead.';
    case 'server':
      return `paste.rs is temporarily unavailable (server error ${error.status ?? 'unknown'}). Try again later, or use Share or Copy instead.`;
    case 'client': {
      const detail = sanitizePasteRsResponse(error.responseBody);
      return `paste.rs rejected the upload (status ${error.status ?? 'unknown'})${detail ? `: ${detail}` : '.'} Use Share or Copy instead.`;
    }
    case 'invalid-response':
      return 'paste.rs returned an invalid upload link. Use Share or Copy instead.';
  }
}

function retryDelayMs(retryAfter: string | null | undefined, now: number): number {
  if (!retryAfter) return PASTE_RS_RETRY_BACKOFF_MS;

  const seconds = Number(retryAfter);
  const requestedMs = Number.isFinite(seconds)
    ? seconds * 1_000
    : Date.parse(retryAfter) - now;
  if (!Number.isFinite(requestedMs)) return PASTE_RS_RETRY_BACKOFF_MS;
  return Math.max(0, Math.min(PASTE_RS_MAX_RETRY_DELAY_MS, requestedMs));
}

function createNewestLogTail(body: string): {
  body: string;
  clientTruncated: boolean;
  originalBytes: number;
  uploadedBytes: number;
} {
  const encoded = textEncoder.encode(body);
  if (encoded.length <= PASTE_RS_TAIL_MAX_BYTES) {
    return {
      body,
      clientTruncated: false,
      originalBytes: encoded.length,
      uploadedBytes: encoded.length,
    };
  }

  let omittedBytes = encoded.length;
  let uploadBody = '';
  for (let pass = 0; pass < 4; pass += 1) {
    const marker =
      `# Earlier debug log content omitted locally before upload ` +
      `(omitted_bytes=${omittedBytes}). Only the newest log tail follows.\n`;
    const markerBytes = textEncoder.encode(marker).length;
    const tailBudget = Math.max(0, PASTE_RS_TAIL_MAX_BYTES - markerBytes);
    let tailStart = Math.max(0, encoded.length - tailBudget);

    // Do not start inside a multi-byte UTF-8 sequence.
    while (tailStart < encoded.length && (encoded[tailStart] & 0xc0) === 0x80) {
      tailStart += 1;
    }

    uploadBody = marker + textDecoder.decode(encoded.slice(tailStart));
    if (tailStart === omittedBytes) break;
    omittedBytes = tailStart;
  }

  return {
    body: uploadBody,
    clientTruncated: true,
    originalBytes: encoded.length,
    uploadedBytes: textEncoder.encode(uploadBody).length,
  };
}

async function runPasteRsAttempt(
  body: string,
  fetchImpl: typeof fetch,
  timeoutMs: number,
): Promise<{ url: string; truncated: boolean }> {
  const controller = new AbortController();
  let timedOut = false;
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  const timeout = new Promise<never>((_, reject) => {
    timeoutId = setTimeout(() => {
      timedOut = true;
      controller.abort();
      reject(new PasteRsAttemptError('timeout'));
    }, timeoutMs);
  });

  try {
    const request = (async () => {
      const response = await fetchImpl(PASTE_RS_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain' },
        body,
        signal: controller.signal,
      });
      const raw = (await response.text()).trim();

      if (response.status === 201 || response.status === 206) {
        let parsed: URL;
        try {
          parsed = new URL(raw);
        } catch {
          throw new PasteRsAttemptError('invalid-response', response.status);
        }
        if (parsed.protocol !== 'https:' || parsed.hostname !== 'paste.rs') {
          throw new PasteRsAttemptError('invalid-response', response.status);
        }
        return { url: raw, truncated: response.status === 206 };
      }

      const retryAfter = response.headers?.get?.('Retry-After');
      if (response.status === 429) {
        throw new PasteRsAttemptError('rate-limit', response.status, raw, retryAfter);
      }
      if (response.status === 0) {
        throw new PasteRsAttemptError('network', response.status, raw, retryAfter);
      }
      if (response.status >= 500 && response.status <= 599) {
        throw new PasteRsAttemptError('server', response.status, raw, retryAfter);
      }
      throw new PasteRsAttemptError('client', response.status, raw, retryAfter);
    })();
    return await Promise.race([request, timeout]);
  } catch (error) {
    if (error instanceof PasteRsAttemptError) throw error;
    if (
      timedOut ||
      (error instanceof Error && error.name === 'AbortError')
    ) {
      throw new PasteRsAttemptError('timeout');
    }
    throw new PasteRsAttemptError('network');
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}

async function runPasteCnetAttempt(
  body: string,
  fetchImpl: typeof fetch,
  timeoutMs: number,
): Promise<{ url: string; deleteKey?: string }> {
  const controller = new AbortController();
  let timedOut = false;
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  const timeout = new Promise<never>((_, reject) => {
    timeoutId = setTimeout(() => {
      timedOut = true;
      controller.abort();
      reject(new PasteRsAttemptError('timeout'));
    }, timeoutMs);
  });

  try {
    const request = (async () => {
      const response = await fetchImpl(PASTE_CNET_URL, {
        method: 'POST',
        headers: {
          Accept: 'application/json, */*',
          'Content-Type': 'text/plain',
          'X-UUID': '1',
        },
        body,
        signal: controller.signal,
      });
      const raw = (await response.text()).trim();
      if (response.status < 200 || response.status > 299) {
        const retryAfter = response.headers?.get?.('Retry-After');
        if (response.status === 429) {
          throw new PasteRsAttemptError('rate-limit', response.status, raw, retryAfter);
        }
        if (response.status === 0) {
          throw new PasteRsAttemptError('network', response.status, raw, retryAfter);
        }
        if (response.status >= 500) {
          throw new PasteRsAttemptError('server', response.status, raw, retryAfter);
        }
        throw new PasteRsAttemptError('client', response.status, raw, retryAfter);
      }

      let parsed: unknown;
      try {
        parsed = JSON.parse(raw);
      } catch {
        throw new PasteRsAttemptError('invalid-response', response.status);
      }
      const record = parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null;
      const url = typeof record?.url === 'string' ? record.url.trim() : '';
      const deleteKey = typeof record?.delete_key === 'string' ? record.delete_key.trim() : '';
      let parsedUrl: URL;
      try {
        parsedUrl = new URL(url);
      } catch {
        throw new PasteRsAttemptError('invalid-response', response.status);
      }
      if (parsedUrl.protocol !== 'https:' || parsedUrl.hostname !== 'paste.c-net.org') {
        throw new PasteRsAttemptError('invalid-response', response.status);
      }
      if (!deleteKey) throw new PasteRsAttemptError('invalid-response', response.status);
      return { url, deleteKey };
    })();
    return await Promise.race([request, timeout]);
  } catch (error) {
    if (error instanceof PasteRsAttemptError) throw error;
    if (timedOut || (error instanceof Error && error.name === 'AbortError')) {
      throw new PasteRsAttemptError('timeout');
    }
    throw new PasteRsAttemptError('network');
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}

/** Upload the complete log, using c-net directly when paste.rs cannot hold it whole. */
export async function uploadDebugLog(
  body: string,
  fetchImpl: typeof fetch = fetch,
  options: PasteRsUploadOptions = {},
): Promise<DebugLogUploadResult> {
  const timeoutMs = Math.max(1, options.attemptTimeoutMs ?? PASTE_RS_ATTEMPT_TIMEOUT_MS);
  const sleep = options.sleep ?? ((ms: number) => new Promise((resolve) => setTimeout(resolve, ms)));
  const originalBytes = textEncoder.encode(body).length;
  let attempts = 0;
  let triedPrimary = false;

  // A maximum-size app export is much larger than paste.rs' live full-paste
  // limit. Sending it there creates a public 206 paste that contains only the
  // beginning of the log, so route known-oversized bodies straight to c-net.
  if (originalBytes <= PASTE_RS_MAX_FULL_UPLOAD_BYTES) {
    triedPrimary = true;
    attempts += 1;
    try {
      const result = await runPasteRsAttempt(body, fetchImpl, timeoutMs);
      if (!result.truncated) {
        return {
          ...result,
          provider: 'paste.rs',
          clientTruncated: false,
          attempts,
          originalBytes,
          uploadedBytes: originalBytes,
        };
      }

      // paste.rs has already made the partial body public. Remove it before
      // creating the complete backup copy; otherwise a failed upload silently
      // leaves an inaccessible public paste behind.
      let cleanupError: unknown = null;
      for (let cleanupAttempt = 0; cleanupAttempt < 2; cleanupAttempt += 1) {
        try {
          await deleteDebugLogUpload(result.url, undefined, fetchImpl, timeoutMs);
          cleanupError = null;
          break;
        } catch (error) {
          cleanupError = error;
          if (cleanupAttempt === 0) await sleep(PASTE_RS_RETRY_BACKOFF_MS);
        }
      }
      if (cleanupError) {
        throw new PasteRsUploadError(
          `paste.rs accepted only part of the log, and the app could not remove ` +
          `the partial public copy at ${result.url}. No second copy was created.`,
          attempts,
        );
      }
    } catch (error) {
      if (error instanceof PasteRsUploadError) throw error;
      const primaryFailure = error as PasteRsAttemptError;
      if (primaryFailure.kind === 'timeout' || primaryFailure.kind === 'network') {
        throw new PasteRsUploadError(
          'The public upload result was not confirmed. It may have been accepted, so the app ' +
          'will not create a second copy automatically. Do not retry unless you accept that risk.',
          attempts,
        );
      }
      if (!primaryFailure.transient) {
        throw new PasteRsUploadError(friendlyPasteRsError(primaryFailure), attempts);
      }
    }
  }

  let backupFailure: PasteRsAttemptError;
  attempts += 1;
  try {
    const result = await runPasteCnetAttempt(body, fetchImpl, timeoutMs);
    return {
      url: result.url,
      provider: 'paste.c-net.org',
      ...(result.deleteKey ? { deleteKey: result.deleteKey } : {}),
      truncated: false,
      clientTruncated: false,
      attempts,
      originalBytes,
      // c-net returned success for the exact original body; never report a
      // tail or a provider-side partial as the completed full-log upload.
      uploadedBytes: originalBytes,
    };
  } catch (error) {
    // A timeout or lost response may occur after c-net accepted the POST. A
    // blind retry could create another public copy whose delete key is lost.
    backupFailure = error as PasteRsAttemptError;
  }

  const detail = friendlyPasteRsError(backupFailure)
    .replaceAll('paste.rs', 'the full-capacity upload service');
  throw new PasteRsUploadError(
    `${triedPrimary ? 'The complete debug-log upload failed.' : 'The log was too large for paste.rs.'} ${detail}`,
    attempts,
  );
}

/** Delete an allowlisted public upload without sending a deletion key to another host. */
export async function deleteDebugLogUpload(
  url: string,
  deleteKey?: string,
  fetchImpl: typeof fetch = fetch,
  timeoutMs = PASTE_RS_ATTEMPT_TIMEOUT_MS,
): Promise<void> {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error('The upload link is invalid.');
  }
  const pasteRsOrigin = new URL(PASTE_RS_URL).origin;
  const pasteCnetOrigin = new URL(PASTE_CNET_URL).origin;
  const isPasteRs = parsed.origin === pasteRsOrigin;
  const isPasteCnet = parsed.origin === pasteCnetOrigin;
  if (
    parsed.protocol !== 'https:' ||
    parsed.username !== '' ||
    parsed.password !== '' ||
    (!isPasteRs && !isPasteCnet) ||
    (isPasteCnet && !deleteKey)
  ) {
    throw new Error('This upload cannot be deleted from the app.');
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(1, timeoutMs));
  try {
    const response = await fetchImpl(url, {
      method: 'DELETE',
      ...(isPasteCnet ? { headers: { 'X-Delete-Key': deleteKey as string } } : {}),
      signal: controller.signal,
    });
    // A retained receipt can outlive an ambiguous successful DELETE. A later
    // 404 is positive absence proof and lets the app finish removing the local
    // receipt instead of stranding it forever.
    if ((response.status < 200 || response.status > 299) && response.status !== 404) {
      throw new Error(`The upload host could not delete the log (status ${response.status}).`);
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('The upload host did not confirm deletion in time.');
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Delete the public copy first, then remove its SecureStore capability receipt.
 * A timeout or host failure deliberately leaves the receipt available to retry.
 */
export async function deleteDebugLogUploadAndReceipt(
  receipt: DebugLogUploadReceipt,
  fetchImpl: typeof fetch = fetch,
  timeoutMs = PASTE_RS_ATTEMPT_TIMEOUT_MS,
): Promise<void> {
  const validated = validateDebugLogUploadReceipt(receipt);
  await deleteDebugLogUpload(validated.url, validated.deleteKey, fetchImpl, timeoutMs);
  await SecureStore.deleteItemAsync(DEBUG_LOG_UPLOAD_RECEIPT_KEY);
}

type GlobalErrorUtils = {
  getGlobalHandler?: () => (error: unknown, isFatal?: boolean) => void;
  setGlobalHandler?: (handler: (error: unknown, isFatal?: boolean) => void) => void;
};

let globalHandlersInstalled = false;

/** Test hook — allow reinstalling handlers between Jest cases. */
export function resetGlobalErrorHandlersForTests(): void {
  globalHandlersInstalled = false;
}

/** Log fatal JS errors and unhandled rejections before the process/native layer exits. */
export function installGlobalErrorHandlers(): void {
  if (globalHandlersInstalled) return;
  globalHandlersInstalled = true;

  const utils = (global as typeof global & { ErrorUtils?: GlobalErrorUtils }).ErrorUtils;
  if (utils?.setGlobalHandler) {
    const previous = utils.getGlobalHandler?.();
    utils.setGlobalHandler((error, isFatal) => {
      debugLog.error(
        'global',
        `${isFatal ? 'fatal' : 'js'} trace=${formatErrorTrace(error)}`,
      );
      previous?.(error, isFatal);
    });
  }

  const processLike = global as typeof global & {
    process?: { on?: (event: string, listener: (reason: unknown) => void) => void };
  };
  processLike.process?.on?.('unhandledRejection', (reason) => {
    debugLog.error('global', `unhandledRejection trace=${formatErrorTrace(reason)}`);
  });
}

/**
 * POST plain text to paste.rs. Transient failures get one bounded retry, then
 * one final attempt containing only a UTF-8-safe 128 KiB newest-log tail.
 */
export async function uploadLogsToPasteRs(
  body: string,
  fetchImpl: typeof fetch = fetch,
  options: PasteRsUploadOptions = {},
): Promise<PasteRsUploadResult> {
  const timeoutMs = Math.max(1, options.attemptTimeoutMs ?? PASTE_RS_ATTEMPT_TIMEOUT_MS);
  const sleep = options.sleep ?? ((ms: number) => new Promise((resolve) => setTimeout(resolve, ms)));
  const now = options.now ?? Date.now;
  const originalBytes = textEncoder.encode(body).length;

  let firstFailure: PasteRsAttemptError;
  try {
    const result = await runPasteRsAttempt(body, fetchImpl, timeoutMs);
    return {
      ...result,
      clientTruncated: false,
      attempts: 1,
      originalBytes,
      uploadedBytes: originalBytes,
    };
  } catch (error) {
    firstFailure = error as PasteRsAttemptError;
    if (!firstFailure.transient) {
      throw new PasteRsUploadError(friendlyPasteRsError(firstFailure), 1);
    }
  }

  await sleep(retryDelayMs(firstFailure.retryAfter, now()));

  let secondFailure: PasteRsAttemptError;
  try {
    const result = await runPasteRsAttempt(body, fetchImpl, timeoutMs);
    return {
      ...result,
      clientTruncated: false,
      attempts: 2,
      originalBytes,
      uploadedBytes: originalBytes,
    };
  } catch (error) {
    secondFailure = error as PasteRsAttemptError;
    if (!secondFailure.transient) {
      throw new PasteRsUploadError(friendlyPasteRsError(secondFailure), 2);
    }
  }

  await sleep(retryDelayMs(secondFailure.retryAfter, now()));

  const tail = createNewestLogTail(body);
  try {
    const result = await runPasteRsAttempt(tail.body, fetchImpl, timeoutMs);
    return {
      ...result,
      clientTruncated: tail.clientTruncated,
      attempts: 3,
      originalBytes: tail.originalBytes,
      uploadedBytes: tail.uploadedBytes,
    };
  } catch (error) {
    const finalFailure = error as PasteRsAttemptError;
    throw new PasteRsUploadError(friendlyPasteRsError(finalFailure), 3);
  }
}
