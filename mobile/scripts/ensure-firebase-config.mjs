#!/usr/bin/env node
/**
 * Materialize Firebase config for local export and EAS cloud builds.
 *
 * Sources (first match wins per file):
 *   1. *_B64 env (CI passes base64 from GHA after local materialize)
 *   2. Inline env or EAS file-path env (GOOGLE_SERVICES_JSON / GOOGLE_SERVICE_INFO_PLIST)
 *   3. Existing gitignored file on disk
 *   4. Copy matching .example placeholder
 *
 * EAS: wired via package.json "eas-build-pre-install" (runs before npm install on cloud).
 * Local: preexport:* hooks and mobile-eas-build.yml materialize step.
 */
import { copyFileSync, existsSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const mobileDir = join(root, '..');

/** @param {string} name */
function decodeB64(name) {
  const raw = process.env[name]?.trim();
  if (!raw) return undefined;
  try {
    return Buffer.from(raw, 'base64').toString('utf8');
  } catch {
    console.error(`ensure-firebase-config: invalid base64 for ${name}`);
    process.exit(1);
  }
}

/**
 * @param {string} target Filename under mobile/
 * @param {{ envVar: string; b64Var: string; example: string; inlinePrefix: string }} options
 */
function materialize(target, options) {
  const { envVar, b64Var, example, inlinePrefix } = options;
  const targetPath = join(mobileDir, target);
  const examplePath = join(mobileDir, example);

  const fromB64 = decodeB64(b64Var);
  if (fromB64) {
    writeFileSync(targetPath, fromB64, 'utf8');
    console.log(`ensure-firebase-config: wrote ${target} from ${b64Var}`);
    return;
  }

  const envVal = process.env[envVar]?.trim();
  if (envVal) {
    if (envVal.startsWith(inlinePrefix)) {
      writeFileSync(targetPath, envVal, 'utf8');
      console.log(`ensure-firebase-config: wrote ${target} from ${envVar} (inline)`);
      return;
    }
    const srcPath = isAbsolute(envVal) ? envVal : join(mobileDir, envVal);
    if (existsSync(srcPath)) {
      copyFileSync(srcPath, targetPath);
      console.log(`ensure-firebase-config: copied ${envVar} path → ${target}`);
      return;
    }
    writeFileSync(targetPath, envVal, 'utf8');
    console.log(`ensure-firebase-config: wrote ${target} from ${envVar}`);
    return;
  }

  if (existsSync(targetPath)) {
    console.log(`ensure-firebase-config: ${target} already exists`);
    return;
  }

  if (!existsSync(examplePath)) {
    console.error(`Missing ${example} — cannot materialize ${target}`);
    process.exit(1);
  }
  copyFileSync(examplePath, targetPath);
  console.log(`ensure-firebase-config: copied ${example} → ${target}`);
}

materialize('google-services.json', {
  envVar: 'GOOGLE_SERVICES_JSON',
  b64Var: 'GOOGLE_SERVICES_JSON_B64',
  example: 'google-services.json.example',
  inlinePrefix: '{',
});

materialize('GoogleService-Info.plist', {
  envVar: 'GOOGLE_SERVICE_INFO_PLIST',
  b64Var: 'GOOGLE_SERVICE_INFO_PLIST_B64',
  example: 'GoogleService-Info.plist.example',
  inlinePrefix: '<?xml',
});
