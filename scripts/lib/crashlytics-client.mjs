#!/usr/bin/env node
/**
 * Minimal Firebase Crashlytics REST client (v1alpha reports + issues).
 */
const API_BASE = 'https://firebasecrashlytics.googleapis.com/v1alpha';

/**
 * @param {string} accessToken
 * @param {string} method
 * @param {string} path  e.g. projects/my-proj/apps/1:123:android:abc/reports/topIssues
 * @param {Record<string, string | number | undefined>} [query]
 */
export async function crashlyticsRequest(accessToken, method, path, query = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  const url = `${API_BASE}/${path}${qs ? `?${qs}` : ''}`;
  const response = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: 'application/json',
    },
  });

  const text = await response.text();
  let body;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { raw: text };
  }

  if (!response.ok) {
    const detail = body.error?.message || body.error?.status || text.slice(0, 400);
    const err = new Error(`Crashlytics API ${method} ${path} failed (${response.status}): ${detail}`);
    err.status = response.status;
    err.body = body;
    throw err;
  }
  return body;
}

/**
 * @param {string} projectId
 * @param {string} appId  mobilesdk_app_id, e.g. 1:123:android:abc
 */
export function reportPath(projectId, appId, reportName) {
  const project = encodeURIComponent(projectId);
  const app = encodeURIComponent(appId);
  return `projects/${project}/apps/${app}/reports/${reportName}`;
}

/**
 * @param {string} accessToken
 * @param {string} projectId
 * @param {string} appId
 * @param {object} [options]
 * @returns {Promise<object>}
 */
export async function fetchReport(accessToken, projectId, appId, reportName, options = {}) {
  const path = reportPath(projectId, appId, reportName);
  const query = {
    pageSize: options.pageSize ?? 50,
    pageToken: options.pageToken,
  };
  if (options.filter) {
    query.filter = JSON.stringify(options.filter);
  }
  return crashlyticsRequest(accessToken, 'GET', path, query);
}

/**
 * Paginate a Crashlytics report.
 * @param {string} accessToken
 * @param {string} projectId
 * @param {string} appId
 * @param {string} reportName
 * @param {object} [options]
 * @returns {Promise<object[]>}
 */
export async function fetchAllReportGroups(accessToken, projectId, appId, reportName, options = {}) {
  /** @type {object[]} */
  const groups = [];
  let pageToken;
  do {
    const page = await fetchReport(accessToken, projectId, appId, reportName, {
      ...options,
      pageToken,
    });
    groups.push(...(page.groups || []));
    pageToken = page.nextPageToken || undefined;
  } while (pageToken);
  return groups;
}

/**
 * @param {string} accessToken
 * @param {string} issueName  full resource name
 */
export async function fetchIssue(accessToken, issueName) {
  const path = issueName.replace(/^\/+/, '');
  return crashlyticsRequest(accessToken, 'GET', path);
}

/**
 * @param {string} accessToken
 * @param {string} resourceName  sample event or session resource
 */
export async function fetchResource(accessToken, resourceName) {
  const path = resourceName.replace(/^\/+/, '');
  return crashlyticsRequest(accessToken, 'GET', path);
}

/**
 * @param {number} lookbackDays
 * @returns {object}
 */
export function buildRecentIntervalFilter(lookbackDays) {
  const end = new Date();
  const start = new Date(end.getTime() - lookbackDays * 24 * 60 * 60 * 1000);
  return {
    interval: {
      startTime: start.toISOString(),
      endTime: end.toISOString(),
    },
    issue: {
      state: 'OPEN',
    },
  };
}

/**
 * @param {object} group
 * @returns {{ issue: object, metrics: object } | null}
 */
export function parseIssueGroup(group) {
  const issue = group?.issue;
  if (!issue?.id) return null;
  const metrics = group.metrics?.[0] || {};
  return { issue, metrics };
}
