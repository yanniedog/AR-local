#!/usr/bin/env node
/**
 * Write android release keystore for GHA Gradle builds.
 *
 * Sources (first match wins):
 *   1. ANDROID_KEYSTORE_B64 + ANDROID_KEYSTORE_PASSWORD + ANDROID_KEY_ALIAS + ANDROID_KEY_PASSWORD
 *   2. EXPO_TOKEN — download default keystore from EAS credentials API
 *
 * Outputs keystore path on stdout (for workflow env).
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const mobileDir = join(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = join(mobileDir, 'build', 'signing');
const keystorePath = join(outDir, 'release.keystore');

const EXPO_GRAPHQL = 'https://api.expo.dev/graphql';

function loadAppConfig() {
  const appJson = JSON.parse(readFileSync(join(mobileDir, 'app.json'), 'utf8'));
  const owner = appJson.expo?.owner ?? appJson.owner;
  const slug = appJson.expo?.slug ?? appJson.slug;
  const applicationId = appJson.expo?.android?.package;
  if (!owner || !slug || !applicationId) {
    throw new Error('missing owner, slug, or android.package in app.json');
  }
  return { projectFullName: '@' + owner + '/' + slug, applicationId };
}

async function expoGraphql(query, variables = {}) {
  const token = process.env.EXPO_TOKEN?.trim();
  if (!token) {
    throw new Error('EXPO_TOKEN is not set');
  }
  const res = await fetch(EXPO_GRAPHQL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: 'Bearer ' + token,
    },
    body: JSON.stringify({ query, variables }),
  });
  const body = await res.json();
  if (!res.ok || body.errors?.length) {
    throw new Error('EAS GraphQL failed: ' + JSON.stringify(body.errors ?? body));
  }
  return body.data;
}

async function fromEnvSecrets() {
  const b64 = process.env.ANDROID_KEYSTORE_B64?.trim();
  if (!b64) return null;
  const storePassword = process.env.ANDROID_KEYSTORE_PASSWORD?.trim();
  const keyAlias = process.env.ANDROID_KEY_ALIAS?.trim();
  const keyPassword = process.env.ANDROID_KEY_PASSWORD?.trim();
  if (!storePassword || !keyAlias || !keyPassword) {
    throw new Error(
      'ANDROID_KEYSTORE_B64 set but missing ANDROID_KEYSTORE_PASSWORD, ANDROID_KEY_ALIAS, or ANDROID_KEY_PASSWORD',
    );
  }
  return {
    keystore: Buffer.from(b64, 'base64'),
    storePassword,
    keyAlias,
    keyPassword,
  };
}

const KEYSTORE_QUERY = `
  query AndroidKeystoreForBuild($projectFullName: String!, $applicationIdentifier: String!) {
    app {
      byFullName(fullName: $projectFullName) {
        androidAppCredentials(filter: { applicationIdentifier: $applicationIdentifier, legacyOnly: false }) {
          androidAppBuildCredentialsList {
            isDefault
            androidKeystore {
              keyAlias
              keyPassword
              keystorePassword
              keystore
            }
          }
        }
      }
    }
  }`;

async function fromEas() {
  const { projectFullName, applicationId } = await loadAppConfig();
  const data = await expoGraphql(KEYSTORE_QUERY, {
    projectFullName,
    applicationIdentifier: applicationId,
  });
  const creds = data.app?.byFullName?.androidAppCredentials?.[0];
  const list = creds?.androidAppBuildCredentialsList ?? [];
  const entry =
    list.find((b) => b.isDefault && b.androidKeystore?.keystore) ??
    list.find((b) => b.androidKeystore?.keystore);
  const ks = entry?.androidKeystore;
  if (!ks?.keystore) {
    throw new Error(
      'No EAS Android keystore found for ' +
        applicationId +
        '. Set ANDROID_KEYSTORE_B64 secrets or create keystore on expo.dev.',
    );
  }
  return {
    keystore: Buffer.from(ks.keystore, 'base64'),
    storePassword: ks.keystorePassword,
    keyAlias: ks.keyAlias,
    keyPassword: ks.keyPassword,
  };
}

async function main() {
  const material = (await fromEnvSecrets()) ?? (await fromEas());
  mkdirSync(outDir, { recursive: true });
  writeFileSync(keystorePath, material.keystore);

  const envPath = join(outDir, 'signing.env');
  const lines = [
    'ANDROID_KEYSTORE_PATH=' + keystorePath,
    'ANDROID_KEYSTORE_PASSWORD=' + material.storePassword,
    'ANDROID_KEY_ALIAS=' + material.keyAlias,
    'ANDROID_KEY_PASSWORD=' + material.keyPassword,
  ];
  writeFileSync(envPath, lines.join('\n') + '\n', 'utf8');
  console.log('materialize-android-keystore: wrote ' + keystorePath);
  console.log(keystorePath);
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
