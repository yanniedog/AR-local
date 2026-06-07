// Regenerate the bundled sample payload (mobile/assets/sample/*.json) from a
// built Pi payload directory (the output of `python app_payload.py build`).
//
//   node scripts/build-sample.mjs [pathToAppPayloadDir]
//
// Defaults to ../runs/2026-05-19/_exports/app-payload relative to this repo.
import { gunzipSync } from 'node:zlib';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const mobileDir = resolve(here, '..');
const repoDir = resolve(mobileDir, '..');

const srcDir = process.argv[2]
  ? resolve(process.argv[2])
  : join(repoDir, 'runs', '2026-05-19', '_exports', 'app-payload');
const outDir = join(mobileDir, 'assets', 'sample');
mkdirSync(outDir, { recursive: true });

const manifest = JSON.parse(readFileSync(join(srcDir, 'manifest.json'), 'utf8'));
writeFileSync(join(outDir, 'manifest.json'), JSON.stringify(manifest));

for (const kind of ['core', 'details']) {
  const name = manifest.files[kind].name;
  const gz = readFileSync(join(srcDir, name));
  const json = gunzipSync(gz).toString('utf8');
  writeFileSync(join(outDir, `${kind}.json`), json);
  console.log(`wrote assets/sample/${kind}.json (${(json.length / 1024) | 0} KiB)`);
}
console.log(`sample run_date=${manifest.run_date}`);
