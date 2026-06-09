#!/usr/bin/env node
import crypto from 'node:crypto';
import { readFileSync, unlinkSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const EXPO_GRAPHQL = 'https://api.expo.dev/graphql';
const mobileDir = join(dirname(fileURLToPath(import.meta.url)), '..');

function loadAppConfig() {
  const appJson = JSON.parse(readFileSync(join(mobileDir, 'app.json'), 'utf8'));
  const owner = appJson.expo?.owner ?? appJson.owner;
  const slug = appJson.expo?.slug ?? appJson.slug;
  const applicationId = appJson.expo?.android?.package;
  if (!owner || !slug || !applicationId) {
    console.error('ensure-eas-android-credentials: missing owner, slug, or android.package in app.json');
    process.exit(1);
  }
  return { projectFullName: '@' + owner + '/' + slug, applicationId };
}

async function expoGraphql(query, variables = {}) {
  const token = process.env.EXPO_TOKEN?.trim();
  if (!token) {
    console.error('ensure-eas-android-credentials: EXPO_TOKEN is not set');
    process.exit(1);
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
    console.error('ensure-eas-android-credentials: GraphQL failed', JSON.stringify(body.errors ?? body, null, 2));
    process.exit(1);
  }
  return body.data;
}

function randomHex(bytes = 16) {
  return crypto.randomBytes(bytes).toString('hex');
}

async function generateKeystoreInCloud() {
  const keystoreParams = {
    keystorePassword: randomHex(),
    keyPassword: randomHex(),
    keyAlias: randomHex(),
  };
  const urlData = await expoGraphql(
    'mutation { keystoreGenerationUrl { createKeystoreGenerationUrl { url } } }',
  );
  const url = urlData.keystoreGenerationUrl.createKeystoreGenerationUrl.url;
  const genRes = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(keystoreParams),
  });
  if (!genRes.ok) {
    console.error('ensure-eas-android-credentials: cloud keystore generation HTTP', genRes.status);
    process.exit(1);
  }
  const result = await genRes.json();
  return {
    base64EncodedKeystore: result.keystoreBase64,
    keystorePassword: result.keystorePassword,
    keyAlias: result.keyAlias,
    keyPassword: result.keyPassword,
  };
}

function generateKeystoreWithKeytool() {
  const keystoreParams = {
    keystorePassword: randomHex(),
    keyPassword: randomHex(),
    keyAlias: randomHex(),
  };
  const keystorePath = join(mobileDir, '.tmp-' + randomHex(8) + '-keystore.jks');
  const keytool = spawnSync(
    'keytool',
    [
      '-genkey', '-v', '-storetype', 'JKS',
      '-storepass', keystoreParams.keystorePassword,
      '-keypass', keystoreParams.keyPassword,
      '-keystore', keystorePath,
      '-alias', keystoreParams.keyAlias,
      '-keyalg', 'RSA', '-keysize', '2048', '-validity', '10000',
      '-dname', 'CN=,OU=,O=,L=,S=,C=US',
    ],
    { encoding: 'buffer' },
  );
  if (keytool.status !== 0) {
    return null;
  }
  const keystoreBuf = readFileSync(keystorePath);
  try {
    unlinkSync(keystorePath);
  } catch {
    /* ignore */
  }
  return {
    base64EncodedKeystore: keystoreBuf.toString('base64'),
    keystorePassword: keystoreParams.keystorePassword,
    keyAlias: keystoreParams.keyAlias,
    keyPassword: keystoreParams.keyPassword,
  };
}

const CRED_QUERY = `
  query AndroidCredentials($projectFullName: String!, $applicationIdentifier: String!) {
    app {
      byFullName(fullName: $projectFullName) {
        id
        ownerAccount { id }
        androidAppCredentials(filter: { applicationIdentifier: $applicationIdentifier, legacyOnly: false }) {
          id
          androidAppBuildCredentialsList {
            id
            isDefault
            androidKeystore { id }
          }
        }
      }
    }
  }`;

async function main() {
  const { projectFullName, applicationId } = loadAppConfig();
  const credData = await expoGraphql(CRED_QUERY, {
    projectFullName,
    applicationIdentifier: applicationId,
  });

  const app = credData.app?.byFullName;
  if (!app) {
    console.error('ensure-eas-android-credentials: project not found:', projectFullName);
    process.exit(1);
  }

  const appCredentials = app.androidAppCredentials?.[0];
  const buildList = appCredentials?.androidAppBuildCredentialsList ?? [];
  const defaultWithKeystore = buildList.find((b) => b.isDefault && b.androidKeystore?.id);
  if (defaultWithKeystore) {
    console.log('ensure-eas-android-credentials: default keystore already configured (' + applicationId + ')');
    return;
  }

  const withKeystore = buildList.find((b) => b.androidKeystore?.id);
  if (withKeystore) {
    await expoGraphql(
      'mutation SetDefault($id: ID!) { androidAppBuildCredentials { setDefault(id: $id, isDefault: true) { id } } }',
      { id: withKeystore.id },
    );
    console.log('ensure-eas-android-credentials: set existing build credentials as default');
    return;
  }

  let keystoreInput = generateKeystoreWithKeytool();
  if (!keystoreInput) {
    console.log('ensure-eas-android-credentials: keytool unavailable; using cloud keystore generation');
    keystoreInput = await generateKeystoreInCloud();
  }

  const keystoreCreate = await expoGraphql(
    'mutation CreateKeystore($accountId: ID!, $input: AndroidKeystoreInput!) { androidKeystore { createAndroidKeystore(androidKeystoreInput: $input, accountId: $accountId) { id } } }',
    { accountId: app.ownerAccount.id, input: keystoreInput },
  );
  const keystoreId = keystoreCreate.androidKeystore.createAndroidKeystore.id;

  let androidAppCredentialsId = appCredentials?.id;
  if (!androidAppCredentialsId) {
    const created = await expoGraphql(
      'mutation CreateAppCreds($appId: ID!, $applicationIdentifier: String!) { androidAppCredentials { createAndroidAppCredentials(androidAppCredentialsInput: {}, appId: $appId, applicationIdentifier: $applicationIdentifier) { id } } }',
      { appId: app.id, applicationIdentifier: applicationId },
    );
    androidAppCredentialsId = created.androidAppCredentials.createAndroidAppCredentials.id;
  }

  const buildName = 'Build Credentials ' + applicationId.slice(-12);
  await expoGraphql(
    'mutation CreateBuildCreds($androidAppCredentialsId: ID!, $input: AndroidAppBuildCredentialsInput!) { androidAppBuildCredentials { createAndroidAppBuildCredentials(androidAppBuildCredentialsInput: $input, androidAppCredentialsId: $androidAppCredentialsId) { id } } }',
    {
      androidAppCredentialsId,
      input: { name: buildName, isDefault: true, keystoreId },
    },
  );

  console.log('ensure-eas-android-credentials: created default keystore for ' + applicationId);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
