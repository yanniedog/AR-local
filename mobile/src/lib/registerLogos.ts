import AsyncStorage from '@react-native-async-storage/async-storage';
import { create } from 'zustand';

import { debugLog } from './debugLog';

const REGISTER_URL = 'https://api.cdr.gov.au/cdr-register/v1/banking/data-holders/brands/summary';
const CACHE_KEY = 'ar.registerLogos.v1';
const CACHE_MAX_AGE_MS = 7 * 24 * 3600 * 1000;

const RENDERABLE_RE = /\.(png|jpe?g|gif|webp)(\?[^#]*)?$/i;

const SUFFIX_TOKENS = new Set([
  'ltd',
  'limited',
  'pty',
  'plc',
  'co',
  'the',
  'bank',
  'banks',
  'banking',
  'australia',
  'australian',
  'of',
  'and',
]);

function normalize(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

function tokens(name: string): Set<string> {
  return new Set(
    normalize(name)
      .split(/\s+/)
      .filter((t) => t && !SUFFIX_TOKENS.has(t)),
  );
}

/** Parse CDR Register brand summary into normalized brandName -> logoUri. */
export function parseRegisterPayload(raw: unknown): Record<string, string> {
  const data = raw as { data?: { brandName?: string; logoUri?: string }[] };
  const out: Record<string, string> = {};
  for (const entry of data?.data ?? []) {
    const name = String(entry.brandName ?? '').trim();
    const uri = String(entry.logoUri ?? '').trim();
    if (!name || !uri.toLowerCase().startsWith('https://')) continue;
    if (!RENDERABLE_RE.test(uri)) continue;
    out[normalize(name)] = uri;
  }
  return out;
}

/** Best register logo for a payload provider name (mirrors cdr_brand_logos.py). */
export function logoUriFor(provider: string, register: Record<string, string>): string | undefined {
  if (!register || !Object.keys(register).length) return undefined;
  const norm = normalize(provider);
  if (register[norm]) return register[norm];
  const ptoks = tokens(provider);
  if (!ptoks.size) return undefined;
  let best: string | undefined;
  let bestScore: [number, number] | null = null;
  for (const [name, uri] of Object.entries(register)) {
    const rtoks = tokens(name);
    if (!rtoks.size) continue;
    const rtSubPt = [...rtoks].every((t) => ptoks.has(t));
    const ptSubRt = [...ptoks].every((t) => rtoks.has(t));
    if (!rtSubPt && !ptSubRt) continue;
    const shared = [...rtoks].filter((t) => ptoks.has(t)).length;
    const extra = new Set([...rtoks, ...ptoks]).size - shared;
    const score: [number, number] = [shared, -extra];
    if (bestScore == null || score[0] > bestScore[0] || (score[0] === bestScore[0] && score[1] > bestScore[1])) {
      bestScore = score;
      best = uri;
    }
  }
  return best;
}

interface CachedRegisterLogos {
  savedAt?: number;
  logos?: Record<string, string>;
}

function readCached(raw: string | null): { fresh: Record<string, string> | null; stale: Record<string, string> | null } {
  if (!raw) return { fresh: null, stale: null };
  try {
    const cached = JSON.parse(raw) as CachedRegisterLogos;
    const logos = cached.logos;
    if (!logos || !Object.keys(logos).length) return { fresh: null, stale: null };
    if (typeof cached.savedAt === 'number' && Date.now() - cached.savedAt < CACHE_MAX_AGE_MS) {
      return { fresh: logos, stale: logos };
    }
    return { fresh: null, stale: logos };
  } catch {
    return { fresh: null, stale: null };
  }
}

interface RegisterLogosState {
  logos: Record<string, string>;
  loaded: boolean;
  inflight: Promise<void> | null;
  ensure: () => Promise<void>;
}

export const useRegisterLogosStore = create<RegisterLogosState>((set, get) => ({
  logos: {},
  loaded: false,
  inflight: null,

  async ensure() {
    if (get().loaded) return;
    if (get().inflight) {
      await get().inflight;
      return;
    }
    const task = (async () => {
      let staleLogos: Record<string, string> | null = null;
      try {
        const { fresh, stale } = readCached(await AsyncStorage.getItem(CACHE_KEY));
        staleLogos = stale;
        if (fresh) {
          set({ logos: fresh, loaded: true });
          debugLog.info('registerLogos', `cache hit brands=${Object.keys(fresh).length}`);
          return;
        }
        const res = await fetch(REGISTER_URL, { headers: { 'x-v': '1' } });
        if (!res.ok) throw new Error(`register HTTP ${res.status}`);
        const logos = parseRegisterPayload(await res.json());
        set({ logos, loaded: true });
        await AsyncStorage.setItem(CACHE_KEY, JSON.stringify({ savedAt: Date.now(), logos }));
        debugLog.info('registerLogos', `fetched brands=${Object.keys(logos).length}`);
      } catch (err) {
        debugLog.warn('registerLogos', `fetch failed: ${String((err as Error)?.message ?? err)}`);
        if (staleLogos) {
          set({ logos: staleLogos, loaded: true });
          debugLog.info('registerLogos', `stale cache fallback brands=${Object.keys(staleLogos).length}`);
        } else {
          set({ loaded: true });
        }
      }
    })();
    set({ inflight: task });
    try {
      await task;
    } finally {
      set({ inflight: null });
    }
  },
}));
