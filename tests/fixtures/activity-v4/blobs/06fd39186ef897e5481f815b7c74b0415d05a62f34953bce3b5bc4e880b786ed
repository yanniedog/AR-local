import {
  AppHealthNetworkPolicy,
  AppHealthNetworkPolicyError,
  executeAppHealthRequest,
  type AppHealthNetworkSessionHandle,
} from './appHealth/networkPolicy';
import type {
  AppHealthAuditMode,
  AppHealthNetworkDecision,
  AppHealthNetworkPurpose,
  AppHealthNetworkSnapshot,
  AppHealthSourceContract,
} from './appHealth/types';

interface XhrPrototype {
  open: (method: string, url: string | URL, ...rest: unknown[]) => void;
  send: (body?: unknown) => void;
}

const guardedFetches = new WeakSet<typeof fetch>();

/** The payload transport must use guarded fetch so final redirects are checked. */
export function hasAppHealthFetchGuard(): boolean {
  return guardedFetches.has(globalThis.fetch);
}

export interface AuditTransportTarget {
  fetch: typeof fetch;
  XMLHttpRequest?: { prototype: XhrPrototype };
}

export interface AppHealthTransportGuard {
  allowManifestAssets(urls: readonly string[]): number;
  snapshot(): AppHealthNetworkSnapshot;
  restore(): AppHealthNetworkSnapshot;
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

function canonical(value: string): string | null {
  try {
    const url = new URL(value);
    if ([...url.searchParams.entries()].length === 1 && /^\d+$/.test(url.searchParams.get('_') ?? '')) {
      url.search = '';
    }
    url.hostname = url.hostname.toLowerCase();
    return url.toString();
  } catch {
    return null;
  }
}

function purposeFor(url: string, contract: AppHealthSourceContract): AppHealthNetworkPurpose {
  const normalized = canonical(url);
  if (normalized && normalized === canonical(contract.manifestUrl)) return 'manifest';
  if (normalized && normalized === canonical(contract.datesIndexUrl)) return 'dates-index';
  return 'asset';
}

const GITHUB_RELEASE_DELIVERY_HOSTS = new Set([
  'objects.githubusercontent.com',
  'release-assets.githubusercontent.com',
]);

function acceptedFinalFetchUrl(
  requestedUrl: string,
  response: Response,
  contract: AppHealthSourceContract,
): boolean {
  const finalValue = typeof response.url === 'string' ? response.url : '';
  const requested = canonical(requestedUrl);
  if (!requested || !finalValue) return false;
  const finalCanonical = canonical(finalValue);
  if (finalCanonical === requested) return true;
  try {
    const requestedParsed = new URL(requested);
    const finalParsed = new URL(finalValue);
    return (
      requestedParsed.hostname === 'github.com' &&
      requestedParsed.pathname.startsWith(`/${contract.repo}/releases/download/`) &&
      finalParsed.protocol === 'https:' &&
      !finalParsed.username &&
      !finalParsed.password &&
      !finalParsed.port &&
      !finalParsed.hash &&
      GITHUB_RELEASE_DELIVERY_HOSTS.has(finalParsed.hostname.toLowerCase())
    );
  } catch {
    return false;
  }
}

/**
 * Install one enforceable transport boundary for the whole audit window.
 * Fetch crosses the allowlist and verifies its final URL. XHR is blocked during
 * audits because React Native does not expose redirects before response data is
 * accepted by callers.
 */
export function installAppHealthTransportGuard(options: {
  target: AuditTransportTarget;
  mode: AppHealthAuditMode;
  contract: AppHealthSourceContract;
  declaredAssetUrls?: readonly string[];
}): AppHealthTransportGuard {
  const { target, mode, contract, declaredAssetUrls } = options;
  const policy = new AppHealthNetworkPolicy();
  const handle: AppHealthNetworkSessionHandle = policy.begin({
    mode,
    contract,
    declaredAssetUrls,
  });
  const originalFetch = target.fetch;
  let approvedFetchDepth = 0;
  const guardedFetch: typeof fetch = async (input, init) => {
    const url = requestUrl(input);
    const response = await executeAppHealthRequest(
      policy,
      handle,
      url,
      purposeFor(url, contract),
      () => {
        // React Native implements fetch on top of XMLHttpRequest. Mark only
        // the synchronous XHR created by this already-authorized fetch call;
        // direct XHR remains blocked because its redirect cannot be verified.
        approvedFetchDepth += 1;
        try {
          return Reflect.apply(originalFetch, target, [input, init]) as ReturnType<typeof fetch>;
        } finally {
          approvedFetchDepth -= 1;
        }
      },
    );
    if (!acceptedFinalFetchUrl(url, response, contract)) {
      policy.recordPolicyViolation(handle);
      throw new AppHealthNetworkPolicyError({ allowed: false, reason: 'not-allowlisted' });
    }
    return response;
  };
  guardedFetches.add(guardedFetch);
  target.fetch = guardedFetch;

  const xhrPrototype = target.XMLHttpRequest?.prototype;
  const originalOpen = xhrPrototype?.open;
  const originalSend = xhrPrototype?.send;
  const decisions = new WeakMap<object, AppHealthNetworkDecision>();
  const approvedFetchRequests = new WeakSet<object>();
  let guardedOpen: XhrPrototype['open'] | null = null;
  let guardedSend: XhrPrototype['send'] | null = null;
  if (xhrPrototype && originalOpen && originalSend) {
    guardedOpen = function guardedXhrOpen(this: object, method, url, ...rest) {
      if (approvedFetchDepth > 0) {
        approvedFetchRequests.add(this);
        return originalOpen.call(this, method, url, ...rest);
      }
      const rawUrl = String(url);
      decisions.set(this, policy.authorize(handle, rawUrl, purposeFor(rawUrl, contract)));
      return originalOpen.call(this, method, url, ...rest);
    };
    guardedSend = function guardedXhrSend(this: object, body) {
      if (approvedFetchRequests.delete(this)) {
        return originalSend.call(this, body);
      }
      const decision = decisions.get(this) ?? { allowed: false, reason: 'invalid-url' };
      if (!decision.allowed) throw new AppHealthNetworkPolicyError(decision);
      throw new AppHealthNetworkPolicyError(policy.blockAuthorizedTransport(handle, decision));
    };
    xhrPrototype.open = guardedOpen;
    xhrPrototype.send = guardedSend;
  }

  let restored: AppHealthNetworkSnapshot | null = null;
  const snapshot = () => policy.snapshot(handle) ?? restored ?? {
    mode,
    authorizationAttempts: 0,
    authorizedAttempts: 0,
    blockedAttempts: 0,
    transportCalls: 0,
    policyViolations: 0,
  };
  return {
    allowManifestAssets(urls) {
      return policy.declareAssetUrls(handle, urls);
    },
    snapshot,
    restore() {
      if (target.fetch === guardedFetch) target.fetch = originalFetch;
      if (xhrPrototype && guardedOpen && xhrPrototype.open === guardedOpen) {
        xhrPrototype.open = originalOpen!;
      }
      if (xhrPrototype && guardedSend && xhrPrototype.send === guardedSend) {
        xhrPrototype.send = originalSend!;
      }
      restored = policy.end(handle) ?? snapshot();
      return restored;
    },
  };
}
