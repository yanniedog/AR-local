#!/usr/bin/env node
/**
 * Print EAS build status + error message (no secrets logged).
 * Usage: EXPO_TOKEN=… node scripts/fetch-eas-build-error.mjs <buildId>
 */
const buildId = process.argv[2]?.trim();
if (!buildId) {
  console.error('usage: node scripts/fetch-eas-build-error.mjs <buildId>');
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

const body = await res.json();
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
