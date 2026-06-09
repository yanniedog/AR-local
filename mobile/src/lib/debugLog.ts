import AsyncStorage from '@react-native-async-storage/async-storage';

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
const STORAGE_KEY = 'ar-debug-log-tail';

const SECRET_PATTERNS: RegExp[] = [
  /EXPO_TOKEN[=:\s]\S+/gi,
  /Bearer\s+\S+/gi,
  /Authorization:\s*\S+/gi,
  /(?:api[_-]?key|secret|password|token)[=:\s]\S+/gi,
];

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

function formatEntry(entry: LogEntry): string {
  const level = entry.level.toUpperCase().padEnd(5);
  return `${entry.ts} [${level}] ${entry.tag}: ${entry.message}`;
}

function entryBytes(entry: LogEntry): number {
  return formatEntry(entry).length + 1;
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
  buffer.append({
    ts: new Date().toISOString(),
    level,
    tag,
    message: redactSecrets(String(message)),
  });
  notify();
  schedulePersist();
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
  },
  clear(): void {
    buffer.clear();
    notify();
    void AsyncStorage.removeItem(STORAGE_KEY).catch(() => {});
  },
  getText(): string {
    return buffer.getText();
  },
  getEntries(): LogEntry[] {
    return buffer.getEntries();
  },
  subscribe(fn: Listener): () => void {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
  async restoreFromStorage(): Promise<void> {
    try {
      const raw = await AsyncStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const tail = JSON.parse(raw) as LogEntry[];
      if (!Array.isArray(tail)) return;
      for (const entry of tail) {
        if (entry?.ts && entry?.level && entry?.tag && entry?.message) {
          buffer.append(entry);
        }
      }
      notify();
    } catch {
      // ignore corrupt snapshot
    }
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
  const url = (await res.text()).trim();
  if (!url.startsWith('http')) {
    throw new Error(`paste.rs upload failed (${res.status})`);
  }
  if (res.status !== 201 && res.status !== 206) {
    throw new Error(`paste.rs upload failed (${res.status})`);
  }
  return { url, truncated: res.status === 206 };
}
