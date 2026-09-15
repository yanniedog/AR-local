import {
  APP_HEALTH_CHECK_CODES,
  type AppHealthAuditMode,
  type AppHealthCheck,
  type AppHealthNetworkDecision,
  type AppHealthNetworkPurpose,
  type AppHealthNetworkSnapshot,
  type AppHealthSourceContract,
} from './types';

export interface AppHealthNetworkSessionHandle {
  readonly token: number;
}

export interface BeginAppHealthNetworkSessionOptions {
  mode: AppHealthAuditMode;
  contract: AppHealthSourceContract;
  /** Exact manifest-authenticated asset URLs. No broad host permission is inferred. */
  declaredAssetUrls?: readonly string[];
  /** Exact dated manifests selected from the validated dates index. */
  declaredManifestUrls?: readonly string[];
}

interface ActiveSession {
  handle: AppHealthNetworkSessionHandle;
  mode: AppHealthAuditMode;
  contract: AppHealthSourceContract;
  declaredAssetUrls: Set<string>;
  declaredManifestUrls: Set<string>;
  authorizationAttempts: number;
  authorizedAttempts: number;
  blockedAttempts: number;
  transportCalls: number;
  policyViolations: number;
  pendingAuthorizations: number;
}

function canonicalAuditUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    if (
      parsed.protocol !== 'https:' ||
      parsed.username ||
      parsed.password ||
      parsed.port ||
      parsed.hash
    ) {
      return null;
    }
    const params = [...parsed.searchParams.entries()];
    if (params.length > 1) return null;
    if (params.length === 1) {
      const [key, value] = params[0];
      if (key !== '_' || !/^\d+$/.test(value)) return null;
      parsed.search = '';
    }
    parsed.hostname = parsed.hostname.toLowerCase();
    return parsed.toString();
  } catch {
    return null;
  }
}

function exactContractUrl(url: string, expected: string): boolean {
  const actualCanonical = canonicalAuditUrl(url);
  const expectedCanonical = canonicalAuditUrl(expected);
  return actualCanonical != null && actualCanonical === expectedCanonical;
}

function assetBelongsToContract(url: string, contract: AppHealthSourceContract): boolean {
  const canonical = canonicalAuditUrl(url);
  if (!canonical) return false;
  const parsed = new URL(canonical);
  return (
    parsed.hostname === 'github.com' &&
    parsed.pathname.startsWith(`/${contract.repo}/releases/download/`)
  );
}

function datedManifestBelongsToContract(
  url: string,
  contract: AppHealthSourceContract,
): boolean {
  const canonical = canonicalAuditUrl(url);
  if (!canonical) return false;
  const parsed = new URL(canonical);
  const prefix = `/${contract.repo}/releases/download/${contract.datedTagPrefix}`;
  if (parsed.hostname !== 'github.com' || !parsed.pathname.startsWith(prefix)) return false;
  return /^\d{4}-\d{2}-\d{2}\/manifest\.json$/.test(parsed.pathname.slice(prefix.length));
}

function snapshotOf(session: ActiveSession): AppHealthNetworkSnapshot {
  return {
    mode: session.mode,
    authorizationAttempts: session.authorizationAttempts,
    authorizedAttempts: session.authorizedAttempts,
    blockedAttempts: session.blockedAttempts,
    transportCalls: session.transportCalls,
    policyViolations: session.policyViolations,
  };
}

function snapshotContract(contract: AppHealthSourceContract): AppHealthSourceContract {
  return {
    ...contract,
    supportedManifestSchemas: [...contract.supportedManifestSchemas],
    supportedCoreSchemas: [...contract.supportedCoreSchemas],
    requiredSections: [...contract.requiredSections],
    taxonomyRoots: { ...contract.taxonomyRoots },
    requiredAssets: [...contract.requiredAssets],
    optionalAssets: [...contract.optionalAssets],
  };
}

export class AppHealthNetworkPolicy {
  private active: ActiveSession | null = null;

  private nextToken = 1;

  begin(options: BeginAppHealthNetworkSessionOptions): AppHealthNetworkSessionHandle {
    if (this.active) throw new Error('An app-health network session is already active.');
    const handle = Object.freeze({ token: this.nextToken });
    this.nextToken += 1;
    const contract = snapshotContract(options.contract);
    const declaredAssetUrls = new Set<string>();
    for (const url of options.declaredAssetUrls ?? []) {
      const canonical = canonicalAuditUrl(url);
      if (canonical && assetBelongsToContract(canonical, contract)) {
        declaredAssetUrls.add(canonical);
      }
    }
    const declaredManifestUrls = new Set<string>();
    const rollingManifest = canonicalAuditUrl(contract.manifestUrl);
    if (rollingManifest) declaredManifestUrls.add(rollingManifest);
    for (const url of options.declaredManifestUrls ?? []) {
      const canonical = canonicalAuditUrl(url);
      if (canonical && datedManifestBelongsToContract(canonical, contract)) {
        declaredManifestUrls.add(canonical);
      }
    }
    this.active = {
      handle,
      mode: options.mode,
      contract,
      declaredAssetUrls,
      declaredManifestUrls,
      authorizationAttempts: 0,
      authorizedAttempts: 0,
      blockedAttempts: 0,
      transportCalls: 0,
      policyViolations: 0,
      pendingAuthorizations: 0,
    };
    return handle;
  }

  private sessionFor(handle: AppHealthNetworkSessionHandle): ActiveSession | null {
    return this.active?.handle === handle ? this.active : null;
  }

  /** Add only URLs authenticated by a manifest already fetched in this session. */
  declareAssetUrls(
    handle: AppHealthNetworkSessionHandle,
    urls: readonly string[],
  ): number {
    const session = this.sessionFor(handle);
    if (!session || session.mode !== 'live-source') return 0;
    let added = 0;
    for (const url of urls) {
      const value = canonicalAuditUrl(url);
      if (value && assetBelongsToContract(value, session.contract)) {
        const before = session.declaredAssetUrls.size;
        session.declaredAssetUrls.add(value);
        if (session.declaredAssetUrls.size > before) added += 1;
      }
    }
    return added;
  }

  authorize(
    handle: AppHealthNetworkSessionHandle,
    url: string,
    purpose: AppHealthNetworkPurpose,
  ): AppHealthNetworkDecision {
    const session = this.sessionFor(handle);
    if (!session) return { allowed: false, reason: 'inactive-session' };
    session.authorizationAttempts += 1;
    if (session.mode === 'local') {
      session.blockedAttempts += 1;
      return { allowed: false, reason: 'local-mode' };
    }
    const canonical = canonicalAuditUrl(url);
    if (!canonical) {
      session.blockedAttempts += 1;
      return { allowed: false, reason: 'invalid-url' };
    }
    const allowed =
      (purpose === 'manifest' && session.declaredManifestUrls.has(canonical)) ||
      (purpose === 'dates-index' && exactContractUrl(canonical, session.contract.datesIndexUrl)) ||
      (purpose === 'asset' && session.declaredAssetUrls.has(canonical));
    if (allowed) {
      session.authorizedAttempts += 1;
      session.pendingAuthorizations += 1;
      return { allowed: true, reason: 'allowlisted' };
    }
    session.blockedAttempts += 1;
    return { allowed: false, reason: 'not-allowlisted' };
  }

  /** Record the actual transport boundary after an authorization decision. */
  recordTransport(
    handle: AppHealthNetworkSessionHandle,
    decision: AppHealthNetworkDecision,
  ): void {
    const session = this.sessionFor(handle);
    if (!session) return;
    session.transportCalls += 1;
    if (!decision.allowed || session.pendingAuthorizations <= 0) {
      session.policyViolations += 1;
      return;
    }
    session.pendingAuthorizations -= 1;
  }

  /** Consume an authorization without transport when a transport cannot verify redirects. */
  blockAuthorizedTransport(
    handle: AppHealthNetworkSessionHandle,
    decision: AppHealthNetworkDecision,
  ): AppHealthNetworkDecision {
    const session = this.sessionFor(handle);
    if (session && decision.allowed) {
      session.pendingAuthorizations = Math.max(0, session.pendingAuthorizations - 1);
      session.blockedAttempts += 1;
    }
    return { allowed: false, reason: 'not-allowlisted' };
  }

  /** Record a post-transport boundary violation such as an unsafe redirect. */
  recordPolicyViolation(handle: AppHealthNetworkSessionHandle): void {
    const session = this.sessionFor(handle);
    if (session) session.policyViolations += 1;
  }

  snapshot(handle: AppHealthNetworkSessionHandle): AppHealthNetworkSnapshot | null {
    const session = this.sessionFor(handle);
    return session ? snapshotOf(session) : null;
  }

  end(handle: AppHealthNetworkSessionHandle): AppHealthNetworkSnapshot | null {
    const session = this.sessionFor(handle);
    if (!session) return null;
    const snapshot = snapshotOf(session);
    this.active = null;
    return snapshot;
  }
}

export class AppHealthNetworkPolicyError extends Error {
  readonly decision: AppHealthNetworkDecision;

  constructor(decision: AppHealthNetworkDecision) {
    super(`App-health request blocked by network policy (${decision.reason}).`);
    this.name = 'AppHealthNetworkPolicyError';
    this.decision = decision;
  }
}

/** The only helper that should cross the transport boundary during an audit. */
export async function executeAppHealthRequest<T>(
  policy: AppHealthNetworkPolicy,
  handle: AppHealthNetworkSessionHandle,
  url: string,
  purpose: AppHealthNetworkPurpose,
  transport: () => Promise<T>,
): Promise<T> {
  const decision = policy.authorize(handle, url, purpose);
  if (!decision.allowed) throw new AppHealthNetworkPolicyError(decision);
  policy.recordTransport(handle, decision);
  return transport();
}

export function appHealthNetworkCheck(snapshot: AppHealthNetworkSnapshot): AppHealthCheck {
  const localTransport = snapshot.mode === 'local' && snapshot.transportCalls > 0;
  const violation = snapshot.policyViolations > 0 || localTransport;
  const blockedCodePath = snapshot.blockedAttempts > 0;
  const status = violation ? 'fail' : blockedCodePath ? 'warn' : 'pass';
  return {
    id: APP_HEALTH_CHECK_CODES.NETWORK_POLICY,
    code: APP_HEALTH_CHECK_CODES.NETWORK_POLICY,
    label: snapshot.mode === 'local' ? 'Local zero-network policy' : 'Live-source allowlist',
    domain: 'network',
    status,
    metrics: {
      localMode: snapshot.mode === 'local',
      authorizationAttempts: snapshot.authorizationAttempts,
      authorizedAttempts: snapshot.authorizedAttempts,
      blockedAttempts: snapshot.blockedAttempts,
      transportCalls: snapshot.transportCalls,
      policyViolations: snapshot.policyViolations,
    },
    ...(violation
      ? { summary: 'Network activity crossed the audit policy boundary.' }
      : blockedCodePath
        ? { summary: 'A network code path was blocked before transport.' }
        : {}),
  };
}
