import AsyncStorage from '@react-native-async-storage/async-storage';
import * as FileSystem from 'expo-file-system/legacy';

import { bridgeLogToCrashlytics } from './observability';

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
export const LOG_FILE_FLUSH_MS = 100;
export const ANDROID_PACKAGE = 'com.eyex.australianrates';
export const ANDROID_LOG_PATH_HINT = `Android/data/${ANDROID_PACKAGE}/files/logs/ar-local.log`;

const STORAGE_KEY = 'ar-debug-log-tail';
const LOG_DIR = `${FileSystem.documentDirectory ?? ''}logs/`;
const LOG_FILE = `${LOG_DIR}ar-local.log`;

const SECRET_VALUE = String.raw`[^\s,;}"']+`;
const SECRET_PATTERNS: RegExp[] = [
  new RegExp(String.raw`EXPO_TOKEN[=:\s]${SECRET_VALUE}`, "gi"),
  new RegExp(String.raw`Bearer\s+${SECRET_VALUE}`, "gi"),
  new RegExp(String.raw`Authorization:\s*${SECRET_VALUE}`, "gi"),
  new RegExp(String.raw`(?:api[_-]?key|secret|password|token)[=:\s]${SECRET_VALUE}`, "gi"),
  new RegExp(String.raw`"(?:EXPO_TOKEN|api[_-]?key|secret|password|token)"\s*:\s*"[^"]+"`, "gi"),
  new RegExp(String.raw`'(?:EXPO_TOKEN|api[_-]?key|secret|password|token)'\s*:\s*'[^']+'`, "gi"),
];

const LOG_LINE_RE = /^(\S+)\s+\[(\w+)\s*\]\s+([^:]+):\s(.*)$/;

/** Strip likely secrets before lines are stored or uploaded. */
export function redactSecrets(text: string): string {
  let out = text;
  for (const pattern of SECRET_PATTERNS) {
    out = out.replace(pattern, (match) => {
      const key = match.split(/[=:\s]/)[0] ?? 'secret';
      return `${key}=[REDACTED]`;
    });
  }
  return out;
}

export function formatEntry(entry: LogEntry): string {
  const level = entry.level.toUpperCase().padEnd(5);
  return `${entry.ts} [${level}] ${entry.tag}: ${entry.message}`;
}

/** Parse a single persisted log line back into a LogEntry. */
export function parseLogLine(line: string): LogEntry | null {
  const match = line.match(LOG_LINE_RE);
  if (!match) return null;
  const level = match[2].toLowerCase() as LogLevel;
  if (!['debug', 'info', 'warn', 'error'].includes(level)) return null;
  return { ts: match[1], level, tag: match[3].trim(), message: match[4] };
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

function trimFileTail(content: string): string {
  const bytes = textEncoder.encode(content);
  if (bytes.length <= MAX_LOG_FILE_BYTES) return content;
  let start = bytes.length - MAX_LOG_FILE_BYTES;
  while (start < bytes.length && bytes[start] !== 0x0a) start += 1;
  start += 1;
  if (start >= bytes.length) return '';
  return textDecoder.decode(bytes.slice(start));
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
let fileWriteEpoch = 0;

function scheduleFileFlush(): void {
  if (fileFlushTimer) return;
  fileFlushTimer = setTimeout(() => {
    fileFlushTimer = null;
    void flushPendingToFile();
  }, LOG_FILE_FLUSH_MS);
}

async function syncLogFile(appendText: string, epoch: number): Promise<void> {
  if (!FileSystem.documentDirectory) {
    throw new Error('documentDirectory unavailable');
  }
  await ensureLogDir();
  const existing = fileContentCache ?? (await FileSystem.readAsStringAsync(LOG_FILE).catch(() => ''));
  if (epoch !== fileWriteEpoch) return;
  const combined = trimFileTail(existing + appendText);
  await FileSystem.writeAsStringAsync(LOG_FILE, combined);
  if (epoch !== fileWriteEpoch) return;
  fileContentCache = combined;
}

async function flushPendingToFile(): Promise<void> {
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
        return;
      }
      await syncLogFile(batch.join(''), epoch);
    } catch {
      if (epoch === fileWriteEpoch) {
        pendingFileLines.unshift(...batch);
      }
    } finally {
      fileFlushPromise = null;
    }
  })();

  await fileFlushPromise;
}

export class RingBuffer {
  private entries: LogEntry[] = [];
  private bytes = 0;

  append(entry: LogEntry): void {
    this.entries.push(entry);
    this.bytes += entryBytes(entry);
    while (
      this.entries.length > MAX_LOG_LINES ||
      this.bytes > MAX_LOG_BYTES
    ) {
      const removed = this.entries.shift();
      if (!removed) break;
      this.bytes -= entryBytes(removed);
    }
  }

  clear(): void {
    this.entries = [];
    this.bytes = 0;
  }

  loadHistory(history: LogEntry[]): void {
    const merged = [...history, ...this.entries];
    merged.sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
    this.entries = [];
    this.bytes = 0;
    for (const entry of merged) {
      this.append(entry);
    }
  }

  getEntries(): LogEntry[] {
    return [...this.entries];
  }

  getText(): string {
    return this.entries.map(formatEntry).join('\n');
  }

  size(): number {
    return this.entries.length;
  }
}

type Listener = () => void;

const buffer = new RingBuffer();
const listeners = new Set<Listener>();
let persistTimer: ReturnType<typeof setTimeout> | null = null;

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
  const messageRedacted = redactSecrets(String(message));
  const entry: LogEntry = {
    ts: new Date().toISOString(),
    level,
    tag,
    message: messageRedacted,
  };
  buffer.append(entry);
  pendingFileLines.push(formatEntry(entry) + '\n');
  bridgeLogToCrashlytics(level, tag, messageRedacted);
  notify();
  schedulePersist();
  scheduleFileFlush();
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
  async clear(): Promise<void> {
    fileWriteEpoch += 1;
    buffer.clear();
    pendingFileLines = [];
    fileContentCache = null;
    if (fileFlushTimer) {
      clearTimeout(fileFlushTimer);
      fileFlushTimer = null;
    }
    const inFlight = fileFlushPromise;
    fileFlushPromise = null;
    if (inFlight) {
      await inFlight.catch(() => {});
    }
    notify();
    await AsyncStorage.removeItem(STORAGE_KEY).catch(() => {});
    await FileSystem.deleteAsync(LOG_FILE, { idempotent: true }).catch(() => {});
  },
  getText(): string {
    return buffer.getText();
  },
  getEntries(): LogEntry[] {
    return buffer.getEntries();
  },
  getLogFileUri(): string {
    return LOG_FILE;
  },
  getAndroidLogPathHint(): string {
    return ANDROID_LOG_PATH_HINT;
  },
  async flushToFile(): Promise<void> {
    if (fileFlushTimer) {
      clearTimeout(fileFlushTimer);
      fileFlushTimer = null;
    }
    await flushPendingToFile();
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
    buffer.loadHistory(restored);
    notify();
  },
};

/** Format log bundle for paste.rs upload (header + body). */
export function formatLogUploadBody(entriesText: string, meta?: Record<string, string>): string {
  const lines = ['# AR-local mobile debug log', `generated=${new Date().toISOString()}`];
  if (meta) {
    for (const [key, value] of Object.entries(meta)) {
      lines.push(`${key}=${value}`);
    }
  }
  lines.push('', entriesText);
  return lines.join('\n');
}

export const PASTE_RS_URL = 'https://paste.rs/';

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
      const msg = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
      debugLog.error('global', `${isFatal ? 'fatal' : 'js'} ${msg}`);
      void debugLog.flushToFile();
      previous?.(error, isFatal);
    });
  }

  const processLike = global as typeof global & {
    process?: { on?: (event: string, listener: (reason: unknown) => void) => void };
  };
  processLike.process?.on?.('unhandledRejection', (reason) => {
    const msg = reason instanceof Error ? `${reason.name}: ${reason.message}` : String(reason);
    debugLog.error('global', `unhandledRejection ${msg}`);
    void debugLog.flushToFile();
  });
}

/** POST plain text to paste.rs; response body is the paste URL. */
export async function uploadLogsToPasteRs(
  body: string,
  fetchImpl: typeof fetch = fetch,
): Promise<{ url: string; truncated: boolean }> {
  const res = await fetchImpl(PASTE_RS_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body,
  });
  const raw = (await res.text()).trim();
  if (res.status !== 201 && res.status !== 206) {
    const snippet = raw.slice(0, 120);
    throw new Error(`paste.rs upload failed (${res.status}): ${snippet}`);
  }
  if (!raw.startsWith('http')) {
    throw new Error(`paste.rs upload failed (${res.status}): invalid response`);
  }
  return { url: raw, truncated: res.status === 206 };
}
