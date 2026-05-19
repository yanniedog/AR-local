/**
 * Required-bot aliases for wait-for-bots and pr-bot-feedback-check.
 * Keys are short names (gemini, codex, sourcery); values are GitHub logins to match.
 */
export const BOT_ALIASES = {
  gemini: ['gemini-code-assist[bot]', 'google-github-actions-bot[bot]', 'google-github-actions[bot]'],
  codex: ['chatgpt-codex-connector[bot]'],
  sourcery: ['sourcery-ai[bot]'],
};

export const DEFAULT_REQUIRED_KEYS = ['gemini', 'codex', 'sourcery'];

export const OPTIONAL_BOT_LOGINS = [
  'copilot-pull-request-reviewer[bot]',
  'coderabbitai[bot]',
  'greptile-apps[bot]',
];

export function parseRequiredKeys(raw) {
  if (!raw || !String(raw).trim()) return [...DEFAULT_REQUIRED_KEYS];
  return String(raw)
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
}

export function resolveRequiredKeys(argvKeys, envRaw) {
  if (argvKeys?.length) return argvKeys;
  const fromEnv = envRaw ?? process.env.AR_BOT_WAIT_REQUIRED ?? process.env.BOT_WAIT_REQUIRED ?? '';
  return parseRequiredKeys(fromEnv);
}

export function loginsForKey(key) {
  const k = key.toLowerCase();
  if (BOT_ALIASES[k]) return BOT_ALIASES[k];
  if (k.includes('[') || k.includes('-')) return [key];
  return [key];
}

export function allKnownBotLogins(requiredKeys) {
  const set = new Set();
  for (const key of requiredKeys) {
    for (const login of loginsForKey(key)) set.add(login.toLowerCase());
  }
  for (const login of OPTIONAL_BOT_LOGINS) set.add(login.toLowerCase());
  return set;
}

export function loginMatchesRequiredKey(login, key) {
  if (!login) return false;
  const lower = login.toLowerCase();
  return loginsForKey(key).some((alias) => lower === alias.toLowerCase());
}

export function missingRequiredKeys(requiredKeys, seenLogins) {
  const seen = [...(seenLogins || [])];
  return requiredKeys.filter(
    (key) => !seen.some((login) => loginMatchesRequiredKey(login, key)),
  );
}

export function formatRequiredKeys(keys) {
  return keys.map((k) => `${k} (${loginsForKey(k).join(' | ')})`).join(', ');
}
