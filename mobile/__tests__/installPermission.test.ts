import {
  INSTALL_PERMISSION_MIN_API,
  installPermissionPackageUri,
  resolveInstallPermissionState,
} from '../src/lib/installPermission';

describe('installPermission', () => {
  describe('resolveInstallPermissionState', () => {
    it('returns not_applicable on iOS', () => {
      expect(resolveInstallPermissionState('ios', 34, false)).toBe('not_applicable');
    });

    it('returns granted below Android O without checking sideload flag', () => {
      expect(resolveInstallPermissionState('android', 25, false)).toBe('granted');
    });

    it('returns granted when sideload is enabled on Android O+', () => {
      expect(resolveInstallPermissionState('android', 34, true)).toBe('granted');
    });

    it('returns required when sideload is disabled on Android O+', () => {
      expect(resolveInstallPermissionState('android', 34, false)).toBe('required');
    });

    it('uses sideload check when api level is unknown on Android', () => {
      expect(resolveInstallPermissionState('android', null, false)).toBe('required');
      expect(resolveInstallPermissionState('android', undefined, true)).toBe('granted');
    });
  });

  describe('installPermissionPackageUri', () => {
    it('builds a package URI from application id', () => {
      expect(installPermissionPackageUri('com.example.app')).toBe('package:com.example.app');
    });

    it('falls back to the default Android package', () => {
      expect(installPermissionPackageUri(null)).toBe('package:com.eyex.australianrates');
      expect(installPermissionPackageUri('')).toBe('package:com.eyex.australianrates');
    });
  });

  it('documents Android O as the install-permission threshold', () => {
    expect(INSTALL_PERMISSION_MIN_API).toBe(26);
  });
});
