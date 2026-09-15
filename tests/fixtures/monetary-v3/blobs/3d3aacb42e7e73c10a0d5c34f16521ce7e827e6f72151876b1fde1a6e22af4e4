import { InteractionManager } from 'react-native';

/** Fallback so looping progress animations cannot stall yield forever. */
const YIELD_TIMEOUT_MS = 48;

/** Payloads at or above this size yield before synchronous JSON.parse. */
export const HEAVY_JSON_BYTES = 256 * 1024;

function armTimeout(ms: number, cb: () => void): ReturnType<typeof setTimeout> {
  const handle = setTimeout(cb, ms);
  // Avoid keeping Jest (and the RN runtime) alive when a yield outlives a test.
  const maybeTimer = handle as ReturnType<typeof setTimeout> & { unref?: () => void };
  maybeTimer.unref?.();
  return handle;
}

function nextMacrotask(): Promise<void> {
  return new Promise((resolve) => {
    armTimeout(0, resolve);
  });
}

function nextPaintFrame(fallbackMs: number): Promise<void> {
  return new Promise((resolve) => {
    let settled = false;
    let frame: number | null = null;
    let fallback: ReturnType<typeof setTimeout> | null = null;
    const finish = () => {
      if (settled) return;
      settled = true;
      if (fallback) clearTimeout(fallback);
      if (frame != null && typeof cancelAnimationFrame === 'function') {
        cancelAnimationFrame(frame);
      }
      resolve();
    };
    if (typeof requestAnimationFrame === 'function') {
      frame = requestAnimationFrame(finish);
    } else {
      armTimeout(17, finish);
    }
    fallback = armTimeout(Math.max(17, fallbackMs), finish);
  });
}

/** Schedule work after navigation/gesture interactions and return a blur-safe cancellation. */
export function scheduleAfterInteractions(work: () => void): () => void {
  let cancelled = false;
  let settled = false;
  let timeout: ReturnType<typeof setTimeout> | null = null;
  let handle: ReturnType<typeof InteractionManager.runAfterInteractions> | null = null;
  const finish = () => {
    if (cancelled || settled) return;
    settled = true;
    if (timeout) clearTimeout(timeout);
    handle?.cancel?.();
    work();
  };
  try {
    handle = InteractionManager.runAfterInteractions(finish);
  } catch {
    // The timeout below still yields before running required heavy work when
    // InteractionManager is unavailable or throws during navigation.
  }
  // Required warmup must not remain queued forever behind looping loading
  // animations, which hold an InteractionManager interaction by default.
  if (!settled) timeout = armTimeout(YIELD_TIMEOUT_MS, finish);
  return () => {
    cancelled = true;
    if (timeout) clearTimeout(timeout);
    handle?.cancel?.();
  };
}

/**
 * Schedule a state change that would trigger expensive screen derivations after
 * a navigation transition has had time to paint. Navigation animations are not
 * consistently registered with InteractionManager on every Expo/Android
 * combination, so wait at least 300 ms when the configured upper bound permits
 * it. `fallbackMs` is the maximum wait, not the minimum delay.
 */
export function scheduleAfterNavigation(
  work: () => void,
  fallbackMs: number = 500,
): () => void {
  let cancelled = false;
  let settled = false;
  let interactionsDone = false;
  let minimumDelayDone = false;
  let minimumDelay: ReturnType<typeof setTimeout> | null = null;
  let fallback: ReturnType<typeof setTimeout> | null = null;
  let handle: ReturnType<typeof InteractionManager.runAfterInteractions> | null = null;
  const finish = () => {
    if (cancelled || settled) return;
    settled = true;
    if (minimumDelay) clearTimeout(minimumDelay);
    if (fallback) clearTimeout(fallback);
    handle?.cancel?.();
    work();
  };
  const finishWhenReady = () => {
    if (interactionsDone && minimumDelayDone) finish();
  };
  minimumDelay = armTimeout(Math.min(300, Math.max(0, fallbackMs)), () => {
    minimumDelayDone = true;
    finishWhenReady();
  });
  try {
    handle = InteractionManager.runAfterInteractions(() => {
      interactionsDone = true;
      finishWhenReady();
    });
  } catch {
    // The timeout still guarantees the state eventually catches up.
  }
  if (!settled) fallback = armTimeout(Math.max(0, fallbackMs), finish);
  return () => {
    cancelled = true;
    if (minimumDelay) clearTimeout(minimumDelay);
    if (fallback) clearTimeout(fallback);
    handle?.cancel?.();
  };
}

/**
 * Yield the JS thread so React can paint / handle touches before the next
 * heavy sync burst (large JSON.parse, hierarchy rebuild, file IO, etc.).
 *
 * 1. Flush one macrotask so already-queued tab/Settings presses can run.
 * 2. Then wait for `InteractionManager.runAfterInteractions`, racing a short
 *    timeout so an active spinner cannot deadlock — without letting the
 *    zero-delay timer preempt an in-flight gesture/transition.
 */
export async function yieldToUi(timeoutMs: number = YIELD_TIMEOUT_MS): Promise<void> {
  await nextMacrotask();
  await new Promise<void>((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      resolve();
    };
    armTimeout(Math.max(0, timeoutMs), finish);
    try {
      InteractionManager.runAfterInteractions(finish);
    } catch {
      finish();
    }
  });
}

/**
 * Yield once per frame-budget slice for `frames` iterations so queued user
 * input is drained before a long synchronous burst.
 */
export async function yieldToUiFrames(
  frames: number = 2,
  timeoutMs: number = YIELD_TIMEOUT_MS,
): Promise<void> {
  const n = Math.max(1, Math.floor(frames));
  for (let i = 0; i < n; i++) {
    await yieldToUi(timeoutMs);
  }
}

/**
 * Wait for real paint opportunities before mounting the next expensive visual
 * surface. InteractionManager/macrotask yields are useful before CPU work but
 * do not guarantee that React Native committed a frame between state changes.
 * The fallback prevents a backgrounded or suspended renderer from hanging
 * required work forever.
 */
export async function yieldToPaintFrames(
  frames: number = 1,
  fallbackMs: number = 100,
): Promise<void> {
  const n = Math.max(1, Math.floor(frames));
  for (let i = 0; i < n; i += 1) {
    await nextPaintFrame(fallbackMs);
  }
}

/**
 * Parse JSON only after yielding so tab/Settings taps queued ahead of this
 * call are never blocked by the upcoming parse. Large payloads yield twice.
 *
 * Note: `JSON.parse` itself remains synchronous (Hermes has no async parser);
 * callers must still keep post-parse work chunked via {@link yieldToUi}.
 */
export async function parseJsonHeavy<T>(text: string): Promise<T> {
  if (text.length >= HEAVY_JSON_BYTES) {
    await yieldToUiFrames(2);
  } else {
    await yieldToUi();
  }
  return JSON.parse(text) as T;
}
