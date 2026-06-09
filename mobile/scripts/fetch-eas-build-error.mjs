#!/usr/bin/env node
/**
 * Print EAS build status + error message (no secrets logged).
 * Usage: EXPO_TOKEN=… BUILD_ID=… node scripts/fetch-eas-build-error.mjs
 *        EXPO_TOKEN=… node scripts/fetch-eas-build-error.mjs <buildId>
 */
const buildId = (process.env.BUILD_ID || process.argv[2])?.trim();
if (!buildId) {
  console.error('usage: BUILD_ID=… node scripts/fetch-eas-build-error.mjs (or pass <buildId> argv)');
  process.exit(1);
}

const token = process.env.EXPO_TOKEN?.trim();
if (!token) {
  console.error('EXPO_TOKEN is not set');
  process.exit(1);
}

const query = `
  query BuildsByIdQuery($buildId: ID!) {
    builds {
      byId(buildId: $buildId) {
        id
        status
        platform
        error { errorCode message docsUrl }
        artifacts { xcodeBuildLogsUrl buildUrl }
      }
    }
  }`;

const res = await fetch('https://api.expo.dev/graphql', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    Authorization: 'Bearer ' + token,
  },
  body: JSON.stringify({ query, variables: { buildId } }),
});

let body;
try {
  body = await res.json();
} catch {
  console.error('GraphQL failed: non-JSON response (HTTP', res.status, ')');
  process.exit(1);
}

if (!res.ok || body.errors?.length) {
  console.error('GraphQL failed:', JSON.stringify(body.errors ?? body, null, 2));
  process.exit(1);
}

const build = body.data?.builds?.byId;
if (!build) {
  console.error('Build not found:', buildId);
  process.exit(1);
}

console.log(JSON.stringify(build, null, 2));
