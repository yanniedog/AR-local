#!/usr/bin/env node
/**
 * Validate Firebase secrets locally, then sync to EAS (B64 + file-type env).
 * Usage: EAS_PROFILE=preview EXPO_TOKEN=… node scripts/sync-firebase-eas-env.mjs
 */
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { canonicalGoogleServicesJson } from './firebase-json-utils.mjs';

const profile = process.env.EAS_PROFILE?.trim();
if (!profile) {
  console.error('sync-firebase-eas-env: EAS_PROFILE is required');
  process.exit(1);
}
if (!process.env.EXPO_TOKEN?.trim()) {
  console.error('sync-firebase-eas-env: EXPO_TOKEN is required');
  process.exit(1);
}

const eas = ['npx', 'eas-cli@16.14.1'];

/**
 * @param {string[]} args
 * @param {string} label
 */
function runEas(args, label) {
  const result = spawnSync(eas[0], [...eas.slice(1), ...args], {
    stdio: 'inherit',
    env: process.env,
  });
  if (result.status !== 0) {
    console.error(`sync-firebase-eas-env: ${label} failed (exit ${result.status ?? 1})`);
    process.exit(result.status ?? 1);
  }
}

/**
 * @param {string} name
 * @param {'string' | 'file'} type
 * @param {string} value
 * @param {string} [filePath]
 */
function syncEnv(name, type, value, filePath) {
  const createArgs =
    type === 'file'
      ? [
          'env:create',
          '--name',
          name,
          '--type',
          'file',
          '--value',
          filePath,
          '--environment',
          profile,
          '--visibility',
          'secret',
          '--non-interactive',
        ]
      : [
          'env:create',
          '--name',
          name,
          '--value',
          value,
          '--environment',
          profile,
          '--visibility',
          'secret',
          '--non-interactive',
        ];

  const create = spawnSync(eas[0], [...eas.slice(1), ...createArgs], {
    encoding: 'utf8',
    env: process.env,
  });

  if (create.status === 0) {
    console.log(`sync-firebase-eas-env: created ${name} on ${profile}`);
    return;
  }

  const combined = `${create.stdout ?? ''}${create.stderr ?? ''}`;
  if (!combined.includes(`already has an environment variable named "${name}"`)) {
    process.stdout.write(create.stdout ?? '');
    process.stderr.write(create.stderr ?? '');
    process.exit(create.status ?? 1);
  }

  const updateArgs =
    type === 'file'
      ? [
          'env:update',
          profile,
          '--variable-name',
          name,
          '--variable-environment',
          profile,
          '--type',
          'file',
          '--value',
          filePath,
          '--non-interactive',
        ]
      : [
          'env:update',
          profile,
          '--variable-name',
          name,
          '--variable-environment',
          profile,
          '--value',
          value,
          '--non-interactive',
        ];

  runEas(updateArgs, `update ${name}`);
  console.log(`sync-firebase-eas-env: updated ${name} on ${profile}`);
}

const googleRaw = process.env.GOOGLE_SERVICES_JSON?.trim();
if (googleRaw) {
  const canonical = canonicalGoogleServicesJson(googleRaw, 'GOOGLE_SERVICES_JSON secret');
  const b64 = Buffer.from(canonical, 'utf8').toString('base64');
  syncEnv('GOOGLE_SERVICES_JSON_B64', 'string', b64);

  const tmpDir = mkdtempSync(join(tmpdir(), 'ar-eas-firebase-'));
  const tmpFile = join(tmpDir, 'google-services.json');
  writeFileSync(tmpFile, canonical, 'utf8');
  try {
    syncEnv('GOOGLE_SERVICES_JSON', 'file', canonical, tmpFile);
  } finally {
    if (existsSync(tmpDir)) {
      rmSync(tmpDir, { recursive: true, force: true });
    }
  }
}

const plistRaw = process.env.GOOGLE_SERVICE_INFO_PLIST?.trim();
if (plistRaw) {
  if (!plistRaw.startsWith('<')) {
    console.error(
      'sync-firebase-eas-env: GOOGLE_SERVICE_INFO_PLIST must start with "<" (raw plist XML)',
    );
    process.exit(1);
  }
  const b64 = Buffer.from(plistRaw, 'utf8').toString('base64');
  syncEnv('GOOGLE_SERVICE_INFO_PLIST_B64', 'string', b64);

  const tmpDir = mkdtempSync(join(tmpdir(), 'ar-eas-firebase-'));
  const tmpFile = join(tmpDir, 'GoogleService-Info.plist');
  writeFileSync(tmpFile, plistRaw, 'utf8');
  try {
    syncEnv('GOOGLE_SERVICE_INFO_PLIST', 'file', plistRaw, tmpFile);
  } finally {
    if (existsSync(tmpDir)) {
      rmSync(tmpDir, { recursive: true, force: true });
    }
  }
}

console.log(`sync-firebase-eas-env: done (${profile})`);
