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

const SECRET_VALUE = String.raw`[^\s,;}"']+`;
const SECRET_PATTERNS: RegExp[] = [
  new RegExp(String.raw`EXPO_TOKEN[=:\s]${SECRET_VALUE}`, "gi"),
  new RegExp(String.raw`Bearer\s+${SECRET_VALUE}`, "gi"),
  new RegExp(String.raw`Authorization:\s*${SECRET_VALUE}`, "gi"),
  new RegExp(String.raw`(?:api[_-]?key|secret|password|token)[=:\s]${SECRET_VALUE}`, "gi"),
  new RegExp(String.raw`"(?:EXPO_TOKEN|api[_-]?key|secret|password|token)"\s*:\s*"[^"]+"`, "gi"),
  new RegExp(String.raw`'(?:EXPO_TOKEN|api[_-]?key|secret|password|token)'\s*:\s*'[^']+'`, "gi"),
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

const textEncoder = new TextEncoder();

function entryBytes(entry: LogEntry): number {
  return textEncoder.encode(formatEntry(entry) + "\n").length;
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
      const valid = tail.filter(
        (entry): entry is LogEntry =>
          !!(entry?.ts && entry?.level && entry?.tag && entry?.message),
      );
      buffer.loadHistory(valid);
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
