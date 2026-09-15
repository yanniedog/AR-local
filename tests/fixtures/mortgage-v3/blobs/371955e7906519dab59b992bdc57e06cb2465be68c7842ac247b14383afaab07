import {
  APP_HEALTH_CHECK_CODES,
  type AppHealthCheck,
  type AppHealthDisplayEvidence,
  type AppHealthDisplayRole,
  type AppHealthStatus,
  type AppHealthSurfaceContract,
  type AppHealthSurfaceObservation,
} from './types';

interface RoleResult {
  checked: number;
  missing: number;
  failed: number;
  warned: number;
  unavailable: number;
  failedSurfaceIds: string[];
}

function blankRoleResult(): RoleResult {
  return {
    checked: 0,
    missing: 0,
    failed: 0,
    warned: 0,
    unavailable: 0,
    failedSurfaceIds: [],
  };
}

function check(
  code: AppHealthCheck['code'],
  label: string,
  status: AppHealthStatus,
  result: RoleResult,
  summary?: string,
): AppHealthCheck {
  return {
    id: code,
    code,
    label,
    domain: 'display-completeness',
    status,
    metrics: {
      checked: result.checked,
      missing: result.missing,
      failed: result.failed,
      warned: result.warned,
      unavailable: result.unavailable,
    },
    summary,
    ...(result.failedSurfaceIds.length
      ? { localEvidence: { failedSurfaceIds: result.failedSurfaceIds.slice() } }
      : {}),
  };
}

function statusFor(result: RoleResult): AppHealthStatus {
  if (result.failed || result.missing) return 'fail';
  if (result.warned) return 'warn';
  if (result.unavailable) return 'unavailable';
  return result.checked ? 'pass' : 'not-run';
}

function evidenceFor(
  observation: AppHealthSurfaceObservation | undefined,
  role: AppHealthDisplayRole,
): AppHealthDisplayEvidence | undefined {
  return observation?.evidence.find((candidate) => candidate.role === role);
}

function registerMissing(
  result: RoleResult,
  contract: AppHealthSurfaceContract,
  role: AppHealthDisplayRole,
): void {
  if (contract.requiredRoles.includes(role)) {
    result.missing += 1;
    result.failedSurfaceIds.push(contract.id);
  }
}

function evaluateRole(
  role: AppHealthDisplayRole,
  contracts: readonly AppHealthSurfaceContract[],
  observations: ReadonlyMap<string, AppHealthSurfaceObservation>,
): RoleResult {
  const result = blankRoleResult();
  for (const contract of contracts) {
    const observation = observations.get(contract.id);
    const evidence = evidenceFor(observation, role);
    if (!evidence) {
      registerMissing(result, contract, role);
      continue;
    }
    result.checked += 1;

    switch (evidence.role) {
      case 'model': {
        const invalid =
          !Number.isInteger(evidence.sourceCount) ||
          evidence.sourceCount < 0 ||
          !Number.isInteger(evidence.modelCount) ||
          evidence.modelCount < 0 ||
          evidence.modelCount > evidence.sourceCount;
        const unexplainedEmpty =
          evidence.sourceCount > 0 && evidence.modelCount === 0 && !contract.allowsIntentionalEmpty;
        if (invalid || unexplainedEmpty) {
          result.failed += 1;
          result.failedSurfaceIds.push(contract.id);
        }
        break;
      }
      case 'list': {
        const invalid =
          !Number.isInteger(evidence.modelCount) ||
          evidence.modelCount < 0 ||
          !Number.isInteger(evidence.renderedCount) ||
          evidence.renderedCount < 0 ||
          evidence.renderedCount > evidence.modelCount;
        if (invalid || (evidence.modelCount > 0 && evidence.renderedCount === 0)) {
          result.failed += 1;
          result.failedSurfaceIds.push(contract.id);
        }
        break;
      }
      case 'visible': {
        const invalid =
          !Number.isInteger(evidence.expectedMinimum) ||
          evidence.expectedMinimum < 0 ||
          !Number.isInteger(evidence.visibleCount) ||
          evidence.visibleCount < 0;
        if (invalid || evidence.visibleCount < evidence.expectedMinimum) {
          result.failed += 1;
          result.failedSurfaceIds.push(contract.id);
        }
        break;
      }
      case 'empty-state': {
        const list = evidenceFor(observation, 'list');
        const model = evidenceFor(observation, 'model');
        const modelEmpty = list?.role === 'list'
          ? list.modelCount === 0
          : model?.role === 'model'
            ? model.modelCount === 0
            : null;
        if (
          modelEmpty == null ||
          evidence.expected !== modelEmpty ||
          evidence.rendered !== modelEmpty
        ) {
          result.failed += 1;
          result.failedSurfaceIds.push(contract.id);
        }
        break;
      }
      case 'critical-layout': {
        // `measured` is carried separately from general readiness and can only
        // be set by the screen's layout/content-size callback. Dimensions are
        // optional because readiness evidence is deliberately compact; richer
        // probes must supply both dimensions together.
        const hasDimensions = evidence.width != null || evidence.height != null;
        const invalidDimensions = hasDimensions && (
          evidence.width == null ||
          evidence.height == null ||
          !Number.isFinite(evidence.width) ||
          !Number.isFinite(evidence.height) ||
          evidence.width <= 0 ||
          evidence.height <= 0
        );
        if (!evidence.measured || evidence.clipped === true || invalidDimensions) {
          result.failed += 1;
          result.failedSurfaceIds.push(contract.id);
        }
        break;
      }
      case 'chart': {
        const invalid =
          !Number.isInteger(evidence.modelPointCount) ||
          evidence.modelPointCount < 0 ||
          !Number.isInteger(evidence.renderedPointCount) ||
          evidence.renderedPointCount < 0 ||
          evidence.renderedPointCount > evidence.modelPointCount;
        if (
          invalid ||
          (evidence.modelPointCount > 0 &&
            (evidence.renderedPointCount === 0 || !evidence.accessibleSummary)) ||
          (contract.chartRequired && evidence.modelPointCount === 0)
        ) {
          result.failed += 1;
          result.failedSurfaceIds.push(contract.id);
        } else if (evidence.modelPointCount === 0) {
          result.unavailable += 1;
        }
        break;
      }
      case 'logo': {
        const total = evidence.decodedCount + evidence.fallbackCount + evidence.missingCount;
        const invalid =
          !Number.isInteger(evidence.expectedCount) ||
          evidence.expectedCount < 0 ||
          !Number.isInteger(evidence.decodedCount) ||
          evidence.decodedCount < 0 ||
          !Number.isInteger(evidence.fallbackCount) ||
          evidence.fallbackCount < 0 ||
          !Number.isInteger(evidence.missingCount) ||
          evidence.missingCount < 0 ||
          total !== evidence.expectedCount;
        if (invalid || (contract.logosRequired && evidence.missingCount > 0)) {
          result.failed += 1;
          result.failedSurfaceIds.push(contract.id);
        } else if (evidence.missingCount > 0 || evidence.fallbackCount > 0) {
          result.warned += 1;
        }
        break;
      }
    }
  }
  return result;
}

function contractCheck(
  contracts: readonly AppHealthSurfaceContract[],
  observations: readonly AppHealthSurfaceObservation[],
): AppHealthCheck {
  const contractIds = contracts.map((contract) => contract.id);
  const observedIds = observations.map((observation) => observation.surfaceId);
  const duplicateContracts = contractIds.length - new Set(contractIds).size;
  const duplicateObservations = observedIds.length - new Set(observedIds).size;
  const expected = new Set(contractIds);
  const observed = new Set(observedIds);
  const missingSurfaces = [...expected].filter((id) => !observed.has(id));
  const unexpectedSurfaces = [...observed].filter((id) => !expected.has(id));
  let duplicateEvidenceRoles = 0;
  for (const observation of observations) {
    const roles = observation.evidence.map((evidence) => evidence.role);
    duplicateEvidenceRoles += roles.length - new Set(roles).size;
  }
  const failures =
    duplicateContracts +
    duplicateObservations +
    missingSurfaces.length +
    unexpectedSurfaces.length +
    duplicateEvidenceRoles;
  return {
    id: APP_HEALTH_CHECK_CODES.DISPLAY_CONTRACT,
    code: APP_HEALTH_CHECK_CODES.DISPLAY_CONTRACT,
    label: 'Display evidence contract',
    domain: 'display-completeness',
    status: failures ? 'fail' : contracts.length ? 'pass' : 'not-run',
    metrics: {
      plannedSurfaces: contracts.length,
      observedSurfaces: observations.length,
      missingSurfaces: missingSurfaces.length,
      unexpectedSurfaces: unexpectedSurfaces.length,
      duplicateContracts,
      duplicateObservations,
      duplicateEvidenceRoles,
    },
    ...(failures
      ? {
          summary: 'Display observations do not match the declared surface contract.',
          localEvidence: {
            missingSurfaceIds: missingSurfaces,
            unexpectedSurfaceIds: unexpectedSurfaces,
          },
        }
      : {}),
  };
}

const ROLE_CHECKS: readonly {
  role: AppHealthDisplayRole;
  code: AppHealthCheck['code'];
  label: string;
  failureSummary: string;
}[] = [
  {
    role: 'model',
    code: APP_HEALTH_CHECK_CODES.DISPLAY_MODEL,
    label: 'Display model population',
    failureSummary: 'Source data did not produce the expected screen model.',
  },
  {
    role: 'list',
    code: APP_HEALTH_CHECK_CODES.DISPLAY_LIST,
    label: 'Rendered list population',
    failureSummary: 'A non-empty display model produced no rendered rows.',
  },
  {
    role: 'visible',
    code: APP_HEALTH_CHECK_CODES.DISPLAY_VISIBILITY,
    label: 'Visible content',
    failureSummary: 'Rendered content was not visibly present in the viewport.',
  },
  {
    role: 'empty-state',
    code: APP_HEALTH_CHECK_CODES.DISPLAY_EMPTY_STATE,
    label: 'Empty-state accuracy',
    failureSummary: 'The empty-state display did not match the model state.',
  },
  {
    role: 'critical-layout',
    code: APP_HEALTH_CHECK_CODES.DISPLAY_LAYOUT,
    label: 'Critical layout visibility',
    failureSummary: 'Critical content was unmeasured, clipped, or had invalid visible bounds.',
  },
  {
    role: 'chart',
    code: APP_HEALTH_CHECK_CODES.DISPLAY_CHART,
    label: 'Chart rendering',
    failureSummary: 'Chart data did not render with an accessible summary.',
  },
  {
    role: 'logo',
    code: APP_HEALTH_CHECK_CODES.DISPLAY_LOGO,
    label: 'Institution artwork',
    failureSummary: 'Required institution artwork was missing or internally inconsistent.',
  },
];

/**
 * Compare independent source, model, render, visibility, and asset evidence.
 * The caller must not derive two adjacent stages from the same variable.
 */
export function evaluateAppHealthDisplayQuality(
  contracts: readonly AppHealthSurfaceContract[],
  surfaceObservations: readonly AppHealthSurfaceObservation[],
): AppHealthCheck[] {
  const observations = new Map<string, AppHealthSurfaceObservation>();
  for (const observation of surfaceObservations) {
    if (!observations.has(observation.surfaceId)) observations.set(observation.surfaceId, observation);
  }
  return [
    contractCheck(contracts, surfaceObservations),
    ...ROLE_CHECKS.map(({ role, code, label, failureSummary }) => {
      const result = evaluateRole(role, contracts, observations);
      const status = statusFor(result);
      return check(
        code,
        label,
        status,
        result,
        status === 'fail' ? failureSummary : status === 'warn' ? 'Fallback content was used.' : undefined,
      );
    }),
  ];
}
