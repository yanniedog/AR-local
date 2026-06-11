import type { UpdateCheckResult } from '../src/lib/appUpdateLogic';
import { shouldShowUpdateBanner } from '../src/lib/updateBanner';

const installed = { version: '1.0.11', buildNumber: '80' };
const remote = {
  schema_version: 1,
  version: '1.0.12',
  build_number: '81',
  download_url: 'https://example.com/app.apk',
  sha256: 'abc',
};

const available: UpdateCheckResult = { status: 'available', installed, remote, changelogs: [] };

describe('shouldShowUpdateBanner', () => {
  it('shows for an available, undismissed update', () => {
    expect(shouldShowUpdateBanner(available, null)).toBe(true);
  });

  it('hides while no check result exists', () => {
    expect(shouldShowUpdateBanner(null, null)).toBe(false);
  });

  it('hides when the app is current or the check errored', () => {
    expect(shouldShowUpdateBanner({ status: 'current', installed, remote }, null)).toBe(false);
    expect(shouldShowUpdateBanner({ status: 'error', message: 'offline' }, null)).toBe(false);
  });

  it('stays hidden for the dismissed build but returns for the next one', () => {
    expect(shouldShowUpdateBanner(available, '81')).toBe(false);
    expect(shouldShowUpdateBanner(available, '80')).toBe(true);
  });
});
