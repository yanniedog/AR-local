// Regenerate the bundled sample payload through the canonical bounded producer.
//
//   node scripts/build-sample.mjs [pathToAppPayloadDir]
//
// Defaults to ../runs/2026-05-19/_exports/app-payload relative to this repo.
import { spawnSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const mobileDir = resolve(here, '..');
const repoDir = resolve(mobileDir, '..');

const srcDir = process.argv[2]
  ? resolve(process.argv[2])
  : join(repoDir, 'runs', '2026-05-19', '_exports', 'app-payload');
const outDir = join(mobileDir, 'assets', 'sample');
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const result = spawnSync(
  python,
  [join(repoDir, 'app_sample.py'), srcDir, outDir],
  { stdio: 'inherit' },
);
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);
