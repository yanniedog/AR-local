#!/usr/bin/env node
/**
 * Copy Firebase config placeholders when real gitignored files are absent.
 * EAS/local dev: replace with files from Firebase console (see HANDOFF.md).
 */
import { copyFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const mobileDir = join(root, '..');

const pairs = [
  ['google-services.json', 'google-services.json.example'],
  ['GoogleService-Info.plist', 'GoogleService-Info.plist.example'],
];

for (const [target, example] of pairs) {
  const targetPath = join(mobileDir, target);
  const examplePath = join(mobileDir, example);
  if (existsSync(targetPath)) continue;
  if (!existsSync(examplePath)) {
    console.error(`Missing ${example} — cannot materialize ${target}`);
    process.exit(1);
  }
  copyFileSync(examplePath, targetPath);
  console.log(`ensure-firebase-config: copied ${example} → ${target}`);
}
