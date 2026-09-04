/**
 * Bot column roster for the PR bot spreadsheet (rows = PRs, columns = bots).
 * Reviewer services are advisory; this roster is reporting-only.
 */

/** Column order for the spreadsheet (after PR metadata columns). */
export const SPREADSHEET_BOT_KEYS = ['gemini', 'codex', 'sourcery', 'copilot', 'coderabbit', 'greptile'];

export const BOT_KEY_LABELS = {
  gemini: 'Gemini',
  codex: 'Codex',
  sourcery: 'Sourcery',
  copilot: 'Copilot',
  coderabbit: 'CodeRabbit',
  greptile: 'Greptile',
};

const BOT_LOGINS = {
  gemini: [
    'gemini-code-assist',
    'gemini-code-assist[bot]',
    'google-github-actions-bot[bot]',
    'google-github-actions[bot]',
  ],
  codex: ['chatgpt-codex-connector', 'chatgpt-codex-connector[bot]'],
  sourcery: ['sourcery-ai', 'sourcery-ai[bot]'],
  copilot: ['copilot-pull-request-reviewer[bot]'],
  coderabbit: ['coderabbitai[bot]'],
  greptile: ['greptile-apps[bot]'],
};

/**
 * @param {string | null | undefined} login
 * @param {string} key
 * @returns {boolean}
 */
export function loginMatchesBotKey(login, key) {
  if (!login || !key) return false;
  const aliases = BOT_LOGINS[key];
  if (!aliases) return false;
  const lower = login.toLowerCase();
  return aliases.some((alias) => lower === alias.toLowerCase());
}

/**
 * @param {string | null | undefined} login
 * @returns {string | null}
 */
export function loginToBotKey(login) {
  if (!login) return null;
  for (const key of SPREADSHEET_BOT_KEYS) {
    if (loginMatchesBotKey(login, key)) return key;
  }
  return null;
}

export const SPREADSHEET_HEADER = [
  'PR #',
  'Title',
  'Merged At',
  'URL',
  ...SPREADSHEET_BOT_KEYS.map((k) => BOT_KEY_LABELS[k] || k),
];
