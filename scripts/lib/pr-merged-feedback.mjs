/** Bounded, complete feedback snapshot for an explicitly pinned merged PR. */
import { classifyThreads, ghJson } from './gh-pr-review-threads.mjs';

/** Unknown authors cannot turn unresolved feedback into empty or bot-noise evidence. */
export function mergedFeedbackViolations(threads) {
  if (!Array.isArray(threads)) throw new Error('Review threads unavailable');
  return threads.flatMap((thread) => {
    if (thread?.isResolved === true) return [];
    if (thread?.isResolved !== false || !Array.isArray(thread.comments?.nodes)) {
      throw new Error('Incomplete feedback resolution evidence');
    }
    if (!thread.comments.nodes.length || thread.comments.nodes.some((comment) =>
      typeof comment?.author?.login !== 'string' || !comment.author.login.trim())) {
      return [{ kind: 'unresolved-unknown-author', threadId: thread.id }];
    }
    return classifyThreads([thread]);
  });
}

const COMMENTS = `totalCount pageInfo { hasNextPage endCursor }
  nodes { id author { login __typename } body createdAt }`;
const QUERY = `query($owner:String!,$name:String!,$number:Int!,$after:String) {
  repository(owner:$owner,name:$name) { nameWithOwner pullRequest(number:$number) {
    number state merged mergedAt headRefOid baseRefName mergeCommit { oid }
    reviewThreads(first:100,after:$after) { totalCount pageInfo { hasNextPage endCursor }
      nodes { id isResolved comments(first:100) { ${COMMENTS} } }
    }
  } }
}`;
const COMMENT_QUERY = `query($id:ID!,$after:String!) {
  node(id:$id) { ... on PullRequestReviewThread { id comments(first:100,after:$after) { ${COMMENTS} } } }
}`;

export function graphQuery(query, variables) {
  const args = ['api', 'graphql', '-f', `query=${query}`];
  for (const [key, value] of Object.entries(variables)) {
    if (value !== null) args.push(typeof value === 'number' ? '-F' : '-f', `${key}=${value}`);
  }
  const result = ghJson(args);
  if (result.errors?.length) throw new Error('Feedback GraphQL errors');
  return result.data;
}

function page(connection, expectedTotal, seen, cursors) {
  if (!Number.isSafeInteger(connection?.totalCount) || connection.totalCount < 0 ||
      (expectedTotal !== undefined && connection.totalCount !== expectedTotal) ||
      !Array.isArray(connection.nodes) || connection.nodes.length > 100 ||
      typeof connection.pageInfo?.hasNextPage !== 'boolean') throw new Error('Incomplete feedback pagination');
  for (const node of connection.nodes) {
    if (!node || typeof node.id !== 'string' || !node.id || seen.has(node.id)) throw new Error('Duplicate or missing feedback identity');
    seen.add(node.id);
  }
  const { hasNextPage, endCursor } = connection.pageInfo;
  if (hasNextPage) {
    if (!connection.nodes.length || typeof endCursor !== 'string' || !endCursor || cursors.has(endCursor) ||
        seen.size >= connection.totalCount) throw new Error('Invalid feedback cursor');
    cursors.add(endCursor);
  } else if (seen.size !== connection.totalCount) throw new Error('Incomplete feedback count');
  return hasNextPage ? endCursor : null;
}

function completeComments(thread, query) {
  let connection = thread.comments;
  const total = connection?.totalCount, seen = new Set(), cursors = new Set(), nodes = [];
  for (let index = 0; index < 100; index += 1) {
    const after = page(connection, total, seen, cursors);
    for (const comment of connection.nodes) {
      if (typeof comment.body !== 'string' || typeof comment.createdAt !== 'string' ||
          (comment.author !== null && (typeof comment.author?.login !== 'string' ||
            typeof comment.author?.__typename !== 'string'))) throw new Error('Incomplete feedback comment');
    }
    nodes.push(...connection.nodes);
    if (!after) return { nodes };
    const node = query(COMMENT_QUERY, { id: thread.id, after })?.node;
    if (node?.id !== thread.id) throw new Error('Review thread changed during comments read');
    connection = node.comments;
  }
  throw new Error('Feedback comments pagination limit exceeded');
}

export function readMergedFeedback(repository, number, identity, { query = graphQuery } = {}) {
  const [owner, name] = repository.split('/');
  const seen = new Set(), cursors = new Set(), threads = [];
  let after = null, total;
  for (let index = 0; index < 100; index += 1) {
    const result = query(QUERY, { owner, name, number, after });
    const pr = result?.repository?.pullRequest;
    if (result?.repository?.nameWithOwner !== repository || pr?.number !== number ||
        pr.state !== 'MERGED' || pr.merged !== true || pr.mergedAt !== identity.mergedAt ||
        pr.headRefOid !== identity.headSha || pr.mergeCommit?.oid !== identity.mergeSha ||
        pr.baseRefName !== identity.baseRef) throw new Error('Feedback merged identity mismatch');
    const connection = pr.reviewThreads;
    after = page(connection, total, seen, cursors);
    total = connection.totalCount;
    for (const thread of connection.nodes) {
      if (typeof thread.isResolved !== 'boolean') throw new Error('Missing feedback resolution state');
      threads.push({ id: thread.id, isResolved: thread.isResolved, comments: completeComments(thread, query) });
    }
    if (!after) return threads;
  }
  throw new Error('Feedback threads pagination limit exceeded');
}
