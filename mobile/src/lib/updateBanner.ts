import type { UpdateCheckResult } from './appUpdateLogic';

/**
 * Banner shows only for an available update the user has not dismissed.
 * Dismissal is keyed to the remote build number, so the banner returns
 * when a newer build ships.
 */
export function shouldShowUpdateBanner(
  result: UpdateCheckResult | null,
  dismissedBuild: string | null,
): boolean {
  if (!result || result.status !== 'available') return false;
  return String(result.remote.build_number) !== dismissedBuild;
}
