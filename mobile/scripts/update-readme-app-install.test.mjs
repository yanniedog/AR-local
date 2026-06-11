#!/usr/bin/env node
import assert from 'node:assert/strict';
import test from 'node:test';

import { qrReleaseUrl } from './app-release-meta.mjs';
import { buildReadmeInstallSection } from './update-readme-app-install.mjs';
import {
  readmeApkQrBranchName,
  readmeApkQrCommitMessage,
} from './publish-readme-app-install.mjs';

test('qrReleaseUrl appends build cache-bust query', () => {
  const url = qrReleaseUrl('owner/repo', 'app-apk-latest', { bust: '42' });
  assert.equal(
    url,
    'https://github.com/owner/repo/releases/download/app-apk-latest/app-preview-qr.png?v=42',
  );
});

test('buildReadmeInstallSection embeds cache-busted QR from manifest', () => {
  const section = buildReadmeInstallSection({
    repo: 'owner/repo',
    manifestPath: undefined,
  });
  assert.match(section, /!\[Install QR\]\(https:\/\/github\.com\/owner\/repo\/releases\/download\/app-apk-latest\/app-preview-qr\.png\?v=/);
  assert.match(section, /<!-- app-android-install:start -->/);
  assert.match(section, /<!-- app-android-install:end -->/);
});

test('readme APK QR commit message and branch are deterministic', () => {
  assert.equal(
    readmeApkQrCommitMessage('1.0.13', '27'),
    'docs: refresh Android install QR (v1.0.13 build 27) [skip ci]',
  );
  assert.equal(readmeApkQrBranchName('1.0.13', '27'), 'chore/readme-apk-qr-v1.0.13-b27');
});
