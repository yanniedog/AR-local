/** Deterministic product CI; vendor reviews are deliberately absent. */
export const PRODUCT_CI_WORKFLOWS = [
  {
    name: 'app-ci', path: '.github/workflows/app-ci.yml',
    paths: [
      'app_payload*.py', 'app_sample.py', 'contracts/**', 'cdr_*.py', 'cdr_terms/**',
      'pi_*.py', 'laptop_*.py', 'process_safety.py', 'laptop_*.ps1', 'native/**',
      'install_laptop_backup_task*.ps1', 'install_laptop_backup_dispatcher*.ps1',
      'install_laptop_backup_nonadmin_dispatcher*.ps1', 'install_laptop_backup_trusted_dispatcher*.ps1',
      'run_laptop_backup_task.ps1', 'update_laptop_backup_user_session.ps1',
      'run_laptop_backup_dispatcher.ps1', 'run_laptop_backup_nonadmin_dispatcher.ps1',
      'run_laptop_backup_trusted_child.ps1', 'payload_crypto.py', 'release_transport.py',
      'ar_local_pi_runtime.py', 'ar_local_operation_lock.py', 'verify_local*.py',
      'dashboard/**', 'deploy/pi/**', 'scripts/*.py', 'cdr_domain/**', 'cdr_pipeline/**',
      'cleanup_removed_cdr_sector.py', 'requirements.txt', 'requirements-terms.txt',
      'tests/**', '.github/workflows/app-ci.yml',
    ],
    jobs: ['process liveness (Windows)', 'payload builder (pytest)', 'dispatcher contract (Windows PowerShell 5.1)'],
  },
  {
    name: 'app-data-service-ci', path: '.github/workflows/app-data-service-ci.yml',
    paths: ['services/app-data/**', 'app_payload_secure_upload.py', '.github/workflows/app-data-service-ci.yml'],
    jobs: ['service-tests'],
  },
  {
    name: 'historical-candidate-ci', path: '.github/workflows/historical-candidate-ci.yml',
    paths: ['cdr_historical_*.py', 'contracts/historical/**', 'docs/HISTORICAL_CANDIDATE_V1.md',
      'tests/test_cdr_historical_*.py', '.github/workflows/historical-candidate-ci.yml'],
    jobs: ['portable-contract (ubuntu-latest, 3.10)', 'portable-contract (ubuntu-latest, 3.11)',
      'portable-contract (windows-latest, 3.10)', 'portable-contract (windows-latest, 3.11)'],
  },
  {
    name: 'pr-closeout-ci', path: '.github/workflows/pr-closeout-ci.yml',
    paths: ['scripts/**', 'wait_for_bots.mjs', 'package.json', '.github/workflows/**',
      '.github/rulesets/**', '.github/MERGE_POLICY.md', 'WORKFLOW.md', 'AGENTS.md'],
    jobs: ['closeout-contract (ubuntu-latest)', 'closeout-contract (windows-latest)'],
  },
];

/** The policy's supported glob subset is explicit; unsupported syntax fails closed. */
export function pathMatches(file, pattern) {
  if (!/^[A-Za-z0-9_./*\-]+$/.test(pattern)) throw new Error(`Unsupported CI path pattern: ${pattern}`);
  const expression = pattern.split('**').map((part) => part.split('*')
    .map((literal) => literal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('[^/]*')).join('.*');
  return new RegExp(`^${expression}$`).test(file);
}

export function getApplicableProductCi(files) {
  if (!Array.isArray(files)) throw new Error('Changed-file list unavailable');
  const names = files.flatMap((file) => {
    if (typeof file === 'string' && file) return [file];
    if (!file || typeof file.filename !== 'string' || !file.filename ||
        (file.previous_filename != null && (typeof file.previous_filename !== 'string' || !file.previous_filename))) {
      throw new Error('Invalid changed-file entry');
    }
    return [file.filename, file.previous_filename].filter(Boolean);
  });
  return PRODUCT_CI_WORKFLOWS.filter((workflow) => names.some((name) => workflow.paths.some((pattern) => pathMatches(name, pattern))));
}
